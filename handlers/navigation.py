# handlers/navigation.py
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from config import ADMIN_IDS
from keyboards import main_menu_keyboard

router = Router()


async def send_main_menu(target, is_admin: bool):
    """Отправляет главное меню новым сообщением снизу."""
    if isinstance(target, Message):
        await target.answer("🏠 Главное меню:", reply_markup=main_menu_keyboard(is_admin))
    elif isinstance(target, CallbackQuery):
        # Удаляем старое сообщение и отправляем новое снизу
        try:
            await target.message.delete()
        except Exception:
            pass
        await target.message.answer("🏠 Главное меню:", reply_markup=main_menu_keyboard(is_admin))


@router.message(Command("menu"))
async def cmd_menu(message: Message):
    is_admin = message.from_user.id in ADMIN_IDS
    await send_main_menu(message, is_admin)


@router.callback_query(F.data == "menu_back")
async def go_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    is_admin = callback.from_user.id in ADMIN_IDS
    await send_main_menu(callback, is_admin)


@router.callback_query(F.data == "menu_main")
async def menu_main(callback: CallbackQuery, state: FSMContext):
    await go_back(callback, state)


# ── Админ панель ────────────────────────────────────────────────────────────
@router.callback_query(F.data == "admin_panel")
async def admin_panel(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав")

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
            [InlineKeyboardButton(text="⬅️ Назад",               callback_data="menu_back")],
        ])
    )
