# handlers/shop.py
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy import text

from database import Session
from models import Merchandise, Student, Purchase
from states import ItemCreateState, ItemEditState
from config import ADMIN_IDS

router = Router()
PAGE_SIZE = 5


def _stock_emoji(stock: int, bought: bool) -> str:
    if bought:
        return "✅"
    return "🛒" if stock > 0 else "🚫"


async def _get_bought_ids(user_id: int) -> set:
    """Возвращает set merch_id которые купил пользователь."""
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        if not student:
            return set()
        purchases = session.query(Purchase).filter_by(student_id=student.id).all()
        return {p.merch_id for p in purchases}


def _build_shop_kb(items, bought_ids: set, page: int, total: int, is_admin: bool) -> InlineKeyboardMarkup:
    buttons = []
    for item in items:
        bought = item.id in bought_ids
        emoji = _stock_emoji(item.stock, bought)
        label = f"{emoji} {item.name} — {item.price} б. (остаток: {item.stock})"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"view_item_{item.id}_{page}")])

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"shop_page_{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop_shop"))
    if (page + 1) * PAGE_SIZE < total:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"shop_page_{page + 1}"))
    if len(nav) > 1:
        buttons.append(nav)

    buttons.append([InlineKeyboardButton(text="🧾 Мои покупки", callback_data="my_purchases")])
    if is_admin:
        buttons.append([InlineKeyboardButton(text="⚙️ Управление товарами", callback_data="manage_items")])
        buttons.append([InlineKeyboardButton(text="🛍 Статистика магазина",  callback_data="shop_stats_menu")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _show_shop_page(target, page: int, user_id: int):
    with Session() as session:
        all_items = session.query(Merchandise).filter(
            Merchandise.is_deleted == False
        ).order_by(Merchandise.created_at).all()
        total = len(all_items)
        page_items = all_items[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    bought_ids = await _get_bought_ids(user_id)
    is_admin = user_id in ADMIN_IDS
    txt = "🛍 Витрина магазина:" if page_items else "🛍 Магазин пока пуст."
    kb = _build_shop_kb(page_items, bought_ids, page, total, is_admin)

    if isinstance(target, CallbackQuery):
        try:
            await target.message.delete()
        except Exception:
            pass
        await target.message.answer(txt, reply_markup=kb)
    else:
        await target.answer(txt, reply_markup=kb)


@router.callback_query(F.data == "menu_shop")
async def open_shop(callback: CallbackQuery):
    await _show_shop_page(callback, 0, callback.from_user.id)


@router.callback_query(F.data.startswith("shop_page_"))
async def shop_page(callback: CallbackQuery):
    page = int(callback.data.split("_")[2])
    await _show_shop_page(callback, page, callback.from_user.id)


@router.callback_query(F.data == "noop_shop")
async def noop_shop(callback: CallbackQuery):
    await callback.answer()


# ── Мои покупки ──────────────────────────────────────────────────────────────
@router.callback_query(F.data == "my_purchases")
async def my_purchases(callback: CallbackQuery):
    user_id = callback.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        if not student:
            return await callback.answer("❌ Ты не зарегистрирован.", show_alert=True)

        purchases = session.query(Purchase).filter_by(student_id=student.id).all()
        items_info = []
        total_spent = 0
        for p in purchases:
            item = session.query(Merchandise).get(p.merch_id)
            name = item.name if item else "Удалённый товар"
            items_info.append(f"✅ {name} — {p.total_points} б. ({p.purchased_at.strftime('%d.%m.%Y')})")
            total_spent += p.total_points

    if not items_info:
        msg = "🧾 У тебя пока нет покупок."
    else:
        msg = f"🧾 *Мои покупки* ({len(items_info)} шт., потрачено {total_spent} б.):\n\n" + "\n".join(items_info)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_shop")]
    ])
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=kb)


# ── Просмотр товара ──────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("view_item_"))
async def view_item(callback: CallbackQuery):
    parts = callback.data.split("_")
    item_id = int(parts[2])
    shop_pg = int(parts[3]) if len(parts) > 3 else 0
    user_id = callback.from_user.id

    with Session() as session:
        all_items = session.query(Merchandise).filter(
            Merchandise.is_deleted == False
        ).order_by(Merchandise.created_at).all()
        item_ids = [i.id for i in all_items]
        item = session.query(Merchandise).get(item_id)
        student = session.query(Student).filter_by(telegram_id=user_id).first()

        if not item or item.is_deleted:
            return await callback.answer("❌ Товар не найден.", show_alert=True)

        balance = student.balance if student else 0
        can_buy = student and balance >= item.price and item.stock > 0
        already_bought = False
        if student:
            already_bought = session.query(Purchase).filter_by(
                student_id=student.id, merch_id=item_id
            ).first() is not None

        photo_file_id = item.photo_file_id
        item_name, item_desc = item.name, item.description or ""
        item_price, item_stock = item.price, item.stock

    current_idx = item_ids.index(item_id) if item_id in item_ids else 0
    prev_id = item_ids[current_idx - 1] if current_idx > 0 else None
    next_id = item_ids[current_idx + 1] if current_idx < len(item_ids) - 1 else None

    stock_emoji = _stock_emoji(item_stock, already_bought)
    caption = (
        f"{stock_emoji} *{item_name}*\n\n"
        f"{item_desc}\n\n"
        f"💰 Цена: {item_price} баллов\n"
        f"📦 Остаток: {item_stock} шт.\n"
        f"💳 Твой баланс: {balance} баллов"
    )

    buttons = []
    if already_bought:
        buttons.append([InlineKeyboardButton(text="✅ Уже куплено", callback_data="noop_shop")])
    elif item_stock <= 0:
        buttons.append([InlineKeyboardButton(text="🚫 Нет в наличии", callback_data="noop_shop")])
    elif can_buy:
        buttons.append([InlineKeyboardButton(text="🛒 Купить", callback_data=f"confirm_buy_{item_id}")])
    else:
        buttons.append([InlineKeyboardButton(text="❌ Недостаточно баллов", callback_data="noop_shop")])

    nav = []
    if prev_id:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"view_item_{prev_id}_{shop_pg}"))
    nav.append(InlineKeyboardButton(text=f"{current_idx + 1}/{len(item_ids)}", callback_data="noop_shop"))
    if next_id:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"view_item_{next_id}_{shop_pg}"))
    if nav:
        buttons.append(nav)

    buttons.append([InlineKeyboardButton(text="⬅️ Все призы", callback_data=f"shop_page_{shop_pg}")])

    try:
        await callback.message.delete()
    except Exception:
        pass

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    if photo_file_id:
        await callback.message.answer_photo(photo=photo_file_id, caption=caption, parse_mode="Markdown", reply_markup=kb)
    else:
        await callback.message.answer(caption, parse_mode="Markdown", reply_markup=kb)


@router.callback_query(F.data.startswith("confirm_buy_"))
async def confirm_buy(callback: CallbackQuery):
    item_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id

    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        item = session.query(Merchandise).get(item_id)

        if not student:
            return await callback.answer("❌ Ты не зарегистрирован.", show_alert=True)
        if not item or item.is_deleted or item.stock <= 0:
            return await callback.answer("❌ Товар недоступен.", show_alert=True)
        if student.balance < item.price:
            return await callback.answer(f"❌ Нужно {item.price} б., у тебя {student.balance}.", show_alert=True)
        if session.query(Purchase).filter_by(student_id=student.id, merch_id=item_id).first():
            return await callback.answer("❌ Ты уже купил этот товар.", show_alert=True)

        student.balance -= item.price
        item.stock -= 1
        session.add(Purchase(student_id=student.id, merch_id=item_id, quantity=1, total_points=item.price))
        session.commit()
        item_name = item.name

    await callback.answer(f"✅ Куплено: {item_name}!", show_alert=True)


# ── Управление товарами ──────────────────────────────────────────────────────
async def _show_manage(message: Message):
    with Session() as session:
        items = session.query(Merchandise).filter(Merchandise.is_deleted == False).all()
    buttons = []
    for item in items:
        buttons.append([InlineKeyboardButton(
            text=f"{item.name} ({item.stock} шт.)",
            callback_data=f"edititem_{item.id}"
        )])
    buttons.append([InlineKeyboardButton(text="➕ Добавить товар", callback_data="add_item")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_shop")])
    await message.answer("⚙️ Управление товарами:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data == "manage_items")
async def manage_items(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав")
    try:
        await callback.message.delete()
    except Exception:
        pass
    await _show_manage(callback.message)


@router.callback_query(F.data.startswith("edititem_"))
async def edit_item_menu(callback: CallbackQuery, state: FSMContext):
    item_id = int(callback.data.split("_")[1])
    await state.update_data(item_id=item_id)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        "✏️ Что изменить?",
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
async def delete_item(callback: CallbackQuery):
    item_id = int(callback.data.split("_")[1])
    with Session() as session:
        session.execute(text("UPDATE merchandise SET is_deleted = TRUE, stock = 0 WHERE id = :id"), {"id": item_id})
        session.commit()
    await callback.answer("🗑 Товар удалён")
    try:
        await callback.message.delete()
    except Exception:
        pass
    await _show_manage(callback.message)


@router.callback_query(F.data.startswith("edit_"))
async def choose_edit_field(callback: CallbackQuery, state: FSMContext):
    field = callback.data.split("_")[1]
    prompts = {
        "name": "📛 Новое название:", "description": "📄 Новое описание:",
        "price": "💰 Новая цена:", "stock": "📦 Новое количество:", "photo": "🖼 Отправьте фото:",
    }
    state_map = {
        "name": ItemEditState.editing_name, "description": ItemEditState.editing_description,
        "price": ItemEditState.editing_price, "stock": ItemEditState.editing_stock,
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
        session.execute(text("UPDATE merchandise SET name = :v WHERE id = :id"), {"v": message.text.strip(), "id": data["item_id"]})
        session.commit()
    await state.clear()
    await message.answer("✅ Название обновлено")
    await _show_manage(message)


@router.message(ItemEditState.editing_description)
async def edit_description_step(message: Message, state: FSMContext):
    data = await state.get_data()
    with Session() as session:
        session.execute(text("UPDATE merchandise SET description = :v WHERE id = :id"), {"v": message.text.strip(), "id": data["item_id"]})
        session.commit()
    await state.clear()
    await message.answer("✅ Описание обновлено")
    await _show_manage(message)


@router.message(ItemEditState.editing_price)
async def edit_price_step(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        return await message.answer("❗ Введите число")
    data = await state.get_data()
    with Session() as session:
        session.execute(text("UPDATE merchandise SET price = :v WHERE id = :id"), {"v": int(message.text.strip()), "id": data["item_id"]})
        session.commit()
    await state.clear()
    await message.answer("✅ Цена обновлена")
    await _show_manage(message)


@router.message(ItemEditState.editing_stock)
async def edit_stock_step(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        return await message.answer("❗ Введите число")
    data = await state.get_data()
    with Session() as session:
        session.execute(text("UPDATE merchandise SET stock = :v WHERE id = :id"), {"v": int(message.text.strip()), "id": data["item_id"]})
        session.commit()
    await state.clear()
    await message.answer("✅ Количество обновлено")
    await _show_manage(message)


@router.message(ItemEditState.editing_photo, F.photo)
async def edit_photo_step(message: Message, state: FSMContext):
    data = await state.get_data()
    with Session() as session:
        session.execute(text("UPDATE merchandise SET photo_file_id = :v WHERE id = :id"), {"v": message.photo[-1].file_id, "id": data["item_id"]})
        session.commit()
    await state.clear()
    await message.answer("✅ Фото обновлено")
    await _show_manage(message)


@router.callback_query(F.data == "add_item")
async def add_item_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав.")
    await state.clear()
    await callback.message.answer("📛 Введите название товара:")
    await state.set_state(ItemCreateState.AWAITING_NAME)


@router.message(ItemCreateState.AWAITING_NAME)
async def add_item_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("📄 Описание:")
    await state.set_state(ItemCreateState.AWAITING_DESCRIPTION)


@router.message(ItemCreateState.AWAITING_DESCRIPTION)
async def add_item_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await message.answer("💰 Цена:")
    await state.set_state(ItemCreateState.AWAITING_PRICE)


@router.message(ItemCreateState.AWAITING_PRICE)
async def add_item_price(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        return await message.answer("❗ Введите число")
    await state.update_data(price=int(message.text.strip()))
    await message.answer("📦 Количество:")
    await state.set_state(ItemCreateState.AWAITING_STOCK)


@router.message(ItemCreateState.AWAITING_STOCK)
async def add_item_stock(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        return await message.answer("❗ Введите число")
    await state.update_data(stock=int(message.text.strip()))
    await message.answer("🖼 Фото (или напишите «нет»):")
    await state.set_state(ItemCreateState.AWAITING_IMAGE)


@router.message(ItemCreateState.AWAITING_IMAGE, F.photo)
async def add_item_image(message: Message, state: FSMContext):
    await state.update_data(photo_file_id=message.photo[-1].file_id)
    await _finish_item(message, state)


@router.message(ItemCreateState.AWAITING_IMAGE)
async def add_item_no_image(message: Message, state: FSMContext):
    await state.update_data(photo_file_id=None)
    await _finish_item(message, state)


async def _finish_item(message: Message, state: FSMContext):
    data = await state.get_data()
    with Session() as session:
        session.execute(text(
            "INSERT INTO merchandise (name, description, price, stock, photo_file_id, is_deleted, created_at) "
            "VALUES (:name, :desc, :price, :stock, :photo, FALSE, NOW())"
        ), {"name": data["name"], "desc": data["description"],
            "price": data["price"], "stock": data["stock"], "photo": data.get("photo_file_id")})
        session.commit()
    await state.clear()
    await message.answer("✅ Товар добавлен.")
    await _show_manage(message)
