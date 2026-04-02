# handlers/navigation.py
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from sqlalchemy import text

from config import ADMIN_IDS
from keyboards import main_menu_keyboard
from database import Session

router = Router()


async def send_main_menu(target, is_admin: bool):
    kb = main_menu_keyboard(is_admin)
    if isinstance(target, Message):
        await target.answer("🏠 Главное меню:", reply_markup=kb)
    else:
        try:
            await target.message.delete()
        except Exception:
            pass
        await target.message.answer("🏠 Главное меню:", reply_markup=kb)


@router.message(Command("menu"))
async def cmd_menu(message: Message):
    await send_main_menu(message, message.from_user.id in ADMIN_IDS)


@router.callback_query(F.data == "menu_back")
async def go_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await send_main_menu(callback, callback.from_user.id in ADMIN_IDS)


@router.callback_query(F.data == "menu_main")
async def menu_main(callback: CallbackQuery, state: FSMContext):
    await go_back(callback, state)


@router.callback_query(F.data == "admin_panel")
async def admin_panel(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав", show_alert=True)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        "👨‍💼 Админ панель:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 Студенты",             callback_data="students")],
            [InlineKeyboardButton(text="📊 Статистика системы",   callback_data="stats")],
            [InlineKeyboardButton(text="📤 Загрузить сканы",      callback_data="menu_events")],
            [InlineKeyboardButton(text="📑 Модерация заданий",    callback_data="menu_moderation")],
            [InlineKeyboardButton(text="🔄 Обнулить все баллы",   callback_data="reset_all_balances")],
            [InlineKeyboardButton(text="🗑 Обнулить все задания",  callback_data="reset_all_tasks")],
            [InlineKeyboardButton(text="🗑 Обнулить весь магазин", callback_data="reset_all_shop")],
            [InlineKeyboardButton(text="⬅️ Главное меню",         callback_data="menu_back")],
        ])
    )


# ── Обнуление баллов всех ────────────────────────────────────────────────────
@router.callback_query(F.data == "reset_all_balances")
async def confirm_reset_balances(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав", show_alert=True)
    await callback.message.answer(
        "⚠️ Обнуление баллов ВСЕХ студентов. Нельзя отменить. Уверены?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Да", callback_data="do_reset_balances"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_panel"),
        ]])
    )


@router.callback_query(F.data == "do_reset_balances")
async def do_reset_balances(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав", show_alert=True)
    with Session() as session:
        session.execute(text("UPDATE students SET balance = 0"))
        session.commit()
    await callback.answer("✅ Баллы всех студентов обнулены!", show_alert=True)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await admin_panel(callback)


# ── Обнуление заданий ────────────────────────────────────────────────────────
@router.callback_query(F.data == "reset_all_tasks")
async def confirm_reset_tasks(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав", show_alert=True)
    await callback.message.answer(
        "⚠️ Удалить ВСЕ задания и результаты выполнения. Нельзя отменить. Уверены?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Да", callback_data="do_reset_tasks"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_panel"),
        ]])
    )


@router.callback_query(F.data == "do_reset_tasks")
async def do_reset_tasks(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав", show_alert=True)
    with Session() as session:
        session.execute(text("DELETE FROM task_verifications"))
        session.execute(text("UPDATE tasks SET is_deleted = TRUE"))
        session.commit()
    await callback.answer("✅ Задания удалены!", show_alert=True)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await admin_panel(callback)


# ── Обнуление магазина ───────────────────────────────────────────────────────
@router.callback_query(F.data == "reset_all_shop")
async def confirm_reset_shop(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав", show_alert=True)
    await callback.message.answer(
        "⚠️ Удалить ВСЕ товары и покупки. Нельзя отменить. Уверены?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Да", callback_data="do_reset_shop"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_panel"),
        ]])
    )


@router.callback_query(F.data == "do_reset_shop")
async def do_reset_shop(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав", show_alert=True)
    with Session() as session:
        session.execute(text("DELETE FROM purchases"))
        session.execute(text("UPDATE merchandise SET is_deleted = TRUE, stock = 0"))
        session.commit()
    await callback.answer("✅ Магазин очищен!", show_alert=True)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await admin_panel(callback)
