# handlers/navigation.py
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from config import ADMIN_IDS
from keyboards import main_menu_keyboard

router = Router()


# ── /menu — показать главное меню текстовой командой ───────────────────────
@router.message(Command("menu"))
async def cmd_menu(message: Message):
    is_admin = message.from_user.id in ADMIN_IDS
    await message.answer("🏠 Главное меню:", reply_markup=main_menu_keyboard(is_admin))


# ── Кнопка «Назад» → главное меню ─────────────────────────────────────────
@router.callback_query(F.data == "menu_back")
async def go_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    is_admin = callback.from_user.id in ADMIN_IDS
    await callback.message.edit_text(
        "🏠 Главное меню:",
        reply_markup=main_menu_keyboard(is_admin)
    )


# ── callback_data «menu_main» — алиас для menu_back ───────────────────────
@router.callback_query(F.data == "menu_main")
async def menu_main(callback: CallbackQuery, state: FSMContext):
    await go_back(callback, state)
