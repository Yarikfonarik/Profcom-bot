# handlers/shop.py
import os

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from database import Session
from models import Merchandise, Student, Purchase
from states import ItemCreateState, ItemEditState
from config import ADMIN_IDS
from keyboards import main_menu_keyboard

router = Router()


def _build_shop_kb(items, is_admin: bool) -> InlineKeyboardMarkup:
    buttons = []
    for item in items:
        label = f"{item.name} — {item.price} баллов (остаток: {item.stock})"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"view_item_{item.id}")])
    if is_admin:
        buttons.append([InlineKeyboardButton(text="⚙️ Управление товарами", callback_data="manage_items")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ── Открытие магазина ───────────────────────────────────────────────────────
@router.callback_query(F.data == "menu_shop")
async def open_shop(callback: CallbackQuery):
    is_admin = callback.from_user.id in ADMIN_IDS
    with Session() as session:
        items = session.query(Merchandise).filter(Merchandise.stock > 0).all()

    text = "🛍 Доступные товары:" if items else "🛍 Магазин пока пуст."

    # Удаляем старое сообщение и отправляем новое (чтобы кнопка назад работала с фото)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(text, reply_markup=_build_shop_kb(items, is_admin))


# ── Просмотр товара ─────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("view_item_"))
async def view_item(callback: CallbackQuery):
    item_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id

    with Session() as session:
        item = session.query(Merchandise).get(item_id)
        student = session.query(Student).filter_by(telegram_id=user_id).first()

        if not item or item.stock <= 0:
            return await callback.answer("❌ Товар недоступен.", show_alert=True)

        balance = student.balance if student else 0
        can_buy = student and balance >= item.price

        # Проверяем не купил ли уже этот товар
        already_bought = False
        if student:
            already_bought = session.query(Purchase).filter_by(
                student_id=student.id,
                merch_id=item_id
            ).first() is not None

    caption = (
        f"🛍 *{item.name}*\n\n"
        f"{item.description or ''}\n\n"
        f"💰 Цена: {item.price} баллов\n"
        f"📦 Остаток: {item.stock} шт.\n"
        f"💳 Твой баланс: {balance} баллов"
    )

    buttons = []
    if already_bought:
        buttons.append([InlineKeyboardButton(text="✅ Уже куплено", callback_data="no_action")])
    elif can_buy:
        buttons.append([InlineKeyboardButton(text="✅ Купить", callback_data=f"confirm_buy_{item_id}")])
    else:
        buttons.append([InlineKeyboardButton(text="❌ Недостаточно баллов", callback_data="no_action")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_shop")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    try:
        await callback.message.delete()
    except Exception:
        pass

    if item.photo_file_id:
        await callback.message.answer_photo(
            photo=item.photo_file_id,
            caption=caption,
            parse_mode="Markdown",
            reply_markup=kb
        )
    else:
        await callback.message.answer(caption, parse_mode="Markdown", reply_markup=kb)


@router.callback_query(F.data == "no_action")
async def no_action(callback: CallbackQuery):
    await callback.answer()


# ── Подтверждение покупки ───────────────────────────────────────────────────
@router.callback_query(F.data.startswith("confirm_buy_"))
async def confirm_buy(callback: CallbackQuery):
    item_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id

    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        item = session.query(Merchandise).get(item_id)

        if not student:
            return await callback.answer("❌ Ты не зарегистрирован.", show_alert=True)
        if not item or item.stock <= 0:
            return await callback.answer("❌ Товар недоступен.", show_alert=True)
        if student.balance < item.price:
            return await callback.answer(
                f"❌ Недостаточно баллов. Нужно {item.price}, у тебя {student.balance}.",
                show_alert=True
            )
        # Проверка — не купил ли уже
        already = session.query(Purchase).filter_by(
            student_id=student.id, merch_id=item_id
        ).first()
        if already:
            return await callback.answer("❌ Ты уже купил этот товар.", show_alert=True)

        student.balance -= item.price
        item.stock -= 1
        purchase = Purchase(
            student_id=student.id,
            merch_id=item_id,
            quantity=1,
            total_points=item.price
        )
        session.add(purchase)
        session.commit()
        item_name = item.name

    await callback.answer(f"✅ Куплено: {item_name}!", show_alert=True)


# ── Панель управления товарами (админ) ──────────────────────────────────────
@router.callback_query(F.data == "manage_items")
async def manage_items(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав")

    with Session() as session:
        items = session.query(Merchandise).all()

    buttons = []
    for item in items:
        buttons.append([InlineKeyboardButton(
            text=f"{item.name} ({item.stock} шт.)",
            callback_data=f"edititem_{item.id}"
        )])
    buttons.append([InlineKeyboardButton(text="➕ Добавить товар", callback_data="add_item")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад",         callback_data="menu_shop")])

    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        "⚙️ Управление товарами:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


async def _refresh_manage_items(message: Message):
    with Session() as session:
        items = session.query(Merchandise).all()

    buttons = []
    for item in items:
        buttons.append([InlineKeyboardButton(
            text=f"{item.name} ({item.stock} шт.)",
            callback_data=f"edititem_{item.id}"
        )])
    buttons.append([InlineKeyboardButton(text="➕ Добавить товар", callback_data="add_item")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад",         callback_data="menu_shop")])

    await message.answer(
        "⚙️ Управление товарами:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data.startswith("edititem_"))
async def edit_item_menu(callback: CallbackQuery, state: FSMContext):
    item_id = int(callback.data.split("_")[1])
    await state.update_data(item_id=item_id)

    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        "✏️ Что хотите изменить?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📛 Название",     callback_data="edit_name")],
            [InlineKeyboardButton(text="📄 Описание",     callback_data="edit_description")],
            [InlineKeyboardButton(text="💰 Цена",         callback_data="edit_price")],
            [InlineKeyboardButton(text="📦 Кол-во",       callback_data="edit_stock")],
            [InlineKeyboardButton(text="🖼 Фото",         callback_data="edit_photo")],
            [InlineKeyboardButton(text="❌ Удалить товар", callback_data=f"deleteitem_{item_id}")],
            [InlineKeyboardButton(text="⬅️ Назад",        callback_data="manage_items")],
        ])
    )


@router.callback_query(F.data.startswith("deleteitem_"))
async def delete_item(callback: CallbackQuery, state: FSMContext):
    item_id = int(callback.data.split("_")[1])
    with Session() as session:
        item = session.query(Merchandise).get(item_id)
        if item:
            session.delete(item)
            session.commit()
    await callback.answer("🗑 Товар удалён")
    await manage_items(callback)


@router.callback_query(F.data.startswith("edit_"))
async def choose_edit_field(callback: CallbackQuery, state: FSMContext):
    field = callback.data.split("_")[1]
    prompts = {
        "name": "📛 Введите новое название:",
        "description": "📄 Введите новое описание:",
        "price": "💰 Введите новую цену (число):",
        "stock": "📦 Введите новое количество (число):",
        "photo": "🖼 Отправьте новое фото:",
    }
    state_map = {
        "name": ItemEditState.editing_name,
        "description": ItemEditState.editing_description,
        "price": ItemEditState.editing_price,
        "stock": ItemEditState.editing_stock,
        "photo": ItemEditState.editing_photo,
    }
    if field not in prompts:
        return
    await state.set_state(state_map[field])
    await callback.message.answer(prompts[field])


@router.message(ItemEditState.editing_name)
async def edit_name_step(message: Message, state: FSMContext):
    data = await state.get_data()
    with Session() as session:
        item = session.query(Merchandise).get(data["item_id"])
        item.name = message.text.strip()
        session.commit()
    await state.clear()
    await message.answer("✅ Название обновлено")
    await _refresh_manage_items(message)


@router.message(ItemEditState.editing_description)
async def edit_description_step(message: Message, state: FSMContext):
    data = await state.get_data()
    with Session() as session:
        item = session.query(Merchandise).get(data["item_id"])
        item.description = message.text.strip()
        session.commit()
    await state.clear()
    await message.answer("✅ Описание обновлено")
    await _refresh_manage_items(message)


@router.message(ItemEditState.editing_price)
async def edit_price_step(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        return await message.answer("❗ Введите число")
    data = await state.get_data()
    with Session() as session:
        item = session.query(Merchandise).get(data["item_id"])
        item.price = int(message.text.strip())
        session.commit()
    await state.clear()
    await message.answer("✅ Цена обновлена")
    await _refresh_manage_items(message)


@router.message(ItemEditState.editing_stock)
async def edit_stock_step(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        return await message.answer("❗ Введите число")
    data = await state.get_data()
    with Session() as session:
        item = session.query(Merchandise).get(data["item_id"])
        item.stock = int(message.text.strip())
        session.commit()
    await state.clear()
    await message.answer("✅ Количество обновлено")
    await _refresh_manage_items(message)


@router.message(ItemEditState.editing_photo, F.photo)
async def edit_photo_step(message: Message, state: FSMContext):
    data = await state.get_data()
    file_id = message.photo[-1].file_id

    with Session() as session:
        item = session.query(Merchandise).get(data["item_id"])
        item.photo_file_id = file_id
        session.commit()

    await state.clear()
    await message.answer("✅ Фото обновлено")
    await _refresh_manage_items(message)


# ── Добавление нового товара ────────────────────────────────────────────────
@router.callback_query(F.data == "add_item")
async def add_item_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ У вас нет прав.")
    await callback.message.answer("📛 Введите название товара:")
    await state.set_state(ItemCreateState.AWAITING_NAME)


@router.message(ItemCreateState.AWAITING_NAME)
async def add_item_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("📄 Введите описание товара:")
    await state.set_state(ItemCreateState.AWAITING_DESCRIPTION)


@router.message(ItemCreateState.AWAITING_DESCRIPTION)
async def add_item_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await message.answer("💰 Введите цену (число):")
    await state.set_state(ItemCreateState.AWAITING_PRICE)


@router.message(ItemCreateState.AWAITING_PRICE)
async def add_item_price(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        return await message.answer("❗ Введите число")
    await state.update_data(price=int(message.text.strip()))
    await message.answer("📦 Введите количество:")
    await state.set_state(ItemCreateState.AWAITING_STOCK)


@router.message(ItemCreateState.AWAITING_STOCK)
async def add_item_stock(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        return await message.answer("❗ Введите число")
    await state.update_data(stock=int(message.text.strip()))
    await message.answer("🖼 Отправьте фото товара (или напишите «нет» чтобы пропустить):")
    await state.set_state(ItemCreateState.AWAITING_IMAGE)


@router.message(ItemCreateState.AWAITING_IMAGE, F.photo)
async def add_item_image(message: Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await state.update_data(photo_file_id=file_id)
    await _finish_item_creation(message, state)


@router.message(ItemCreateState.AWAITING_IMAGE)
async def add_item_no_image(message: Message, state: FSMContext):
    await state.update_data(photo_file_id=None)
    await _finish_item_creation(message, state)


async def _finish_item_creation(message: Message, state: FSMContext):
    data = await state.get_data()
    with Session() as session:
        new_item = Merchandise(
            name=data["name"],
            description=data["description"],
            price=data["price"],
            stock=data["stock"],
            photo_file_id=data.get("photo_file_id"),
        )
        session.add(new_item)
        session.commit()

    await state.clear()
    await message.answer("✅ Товар успешно добавлен.")
    await _refresh_manage_items(message)
