# handlers/registration.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from models import Student
from states import StudentVerificationState
from database import Session
from config import ADMIN_IDS
from keyboards import main_menu_keyboard, REMOVE_KEYBOARD

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("👋", reply_markup=REMOVE_KEYBOARD)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Начать", callback_data="begin_register")],
        [InlineKeyboardButton(text="🆘 Поддержка", callback_data="support_unreg")],
    ])
    await message.answer("Добро пожаловать! Нажми кнопку ниже, чтобы начать:", reply_markup=kb)


@router.callback_query(F.data == "begin_register")
async def handle_start(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()

    if student:
        is_admin = user_id in ADMIN_IDS
        await callback.message.answer("✅ Ты уже зарегистрирован.", reply_markup=main_menu_keyboard(is_admin))
    else:
        await callback.message.answer(
            "👋 Привет!\n\nВведи свой баркод\n(13 цифр без пробелов)\n\nПример: 2004111111111"
        )
        await state.set_state(StudentVerificationState.AWAITING_BARCODE)


@router.message(StudentVerificationState.AWAITING_BARCODE)
async def register_by_barcode(message: Message, state: FSMContext):
    barcode = message.text.strip()
    if not barcode.isdigit() or len(barcode) != 13:
        return await message.answer("❗ Баркод должен содержать ровно 13 цифр")

    with Session() as session:
        student = session.query(Student).filter_by(barcode=barcode).first()

        if not student:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🆘 Написать в поддержку", callback_data="support_unreg")]
            ])
            return await message.answer(
                "❌ Студент с таким баркодом не найден.\n\n"
                "Обратись в Профком:\n📍 И-108\n📲 https://vk.com/profkom21?from=groups",
                reply_markup=kb
            )

        if student.telegram_id and student.telegram_id != message.from_user.id:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🆘 Написать в поддержку", callback_data="support_unreg")]
            ])
            return await message.answer(
                "⚠️ Этот баркод уже зарегистрирован другим пользователем.\n\n"
                "Обратись в Профком:\n📍 И-108\n📲 https://vk.com/profkom21?from=groups",
                reply_markup=kb
            )

        student.telegram_id = message.from_user.id
        session.commit()

    await state.clear()
    is_admin = message.from_user.id in ADMIN_IDS
    await message.answer("✅ Готово! Ты успешно зарегистрирован.")
    await message.answer("📋 Главное меню:", reply_markup=main_menu_keyboard(is_admin))
