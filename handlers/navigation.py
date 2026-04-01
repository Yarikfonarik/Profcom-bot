# handlers/navigation.py
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from config import ADMIN_IDS
from keyboards import main_menu_keyboard

router = Router()


async def send_main_menu(target, is_admin: bool):
    if isinstance(target, Message):
        await target.answer("🏠 Главное меню:", reply_markup=main_menu_keyboard(is_admin))
    elif isinstance(target, CallbackQuery):
        try:
            await target.message.delete()
        except Exception:
            pass
        await target.message.answer("🏠 Главное меню:", reply_markup=main_menu_keyboard(is_admin))


@router.message(Command("menu"))
async def cmd_menu(message: Message):
    is_admin = message.from_user.id in ADMIN_IDS
    await send_main_menu(message, is_admin)


@router.message(Command("start"))
async def cmd_start_alias(message: Message, state: FSMContext):
    """Алиас — перенаправляет в registration"""
    from handlers.registration import cmd_start
    await cmd_start(message, state)


@router.callback_query(F.data == "menu_back")
async def go_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    is_admin = callback.from_user.id in ADMIN_IDS
    await send_main_menu(callback, is_admin)


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
            [InlineKeyboardButton(text="👥 Студенты",           callback_data="students")],
            [InlineKeyboardButton(text="📊 Статистика системы", callback_data="stats")],
            [InlineKeyboardButton(text="📤 Загрузить сканы",    callback_data="menu_events")],
            [InlineKeyboardButton(text="📑 Модерация заданий",  callback_data="menu_moderation")],
            [InlineKeyboardButton(text="🔄 Обнулить все баллы", callback_data="reset_all_balances")],
            [InlineKeyboardButton(text="⬅️ Главное меню",       callback_data="menu_back")],
        ])
    )


@router.callback_query(F.data == "reset_all_balances")
async def confirm_reset_all(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав", show_alert=True)
    await callback.message.answer(
        "⚠️ *Обнуление баллов всех студентов*\n\n"
        "Это действие обнулит баллы ВСЕХ студентов и не может быть отменено.\n\n"
        "Вы уверены?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, обнулить всех", callback_data="do_reset_all"),
                InlineKeyboardButton(text="❌ Отмена",            callback_data="admin_panel"),
            ]
        ])
    )


@router.callback_query(F.data == "do_reset_all")
async def do_reset_all(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав", show_alert=True)
    from database import Session
    from sqlalchemy import text
    with Session() as session:
        session.execute(text("UPDATE students SET balance = 0"))
        session.commit()
    await callback.answer("✅ Баллы всех студентов обнулены!", show_alert=True)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await admin_panel(callback)
