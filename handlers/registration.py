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
    await message.answer(
        "🚀 *Добро пожаловать!*\n\nНажми кнопку чтобы начать.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Начало", callback_data="begin_register")],
            [InlineKeyboardButton(text="🆘 Поддержка", callback_data="support_unreg")],
        ])
    )


@router.callback_query(F.data == "begin_register")
async def handle_start(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()

    if student:
        is_admin = user_id in ADMIN_IDS
        try: await callback.message.delete()
        except Exception: pass
        await callback.message.answer("🏠 Главное меню:", reply_markup=main_menu_keyboard(is_admin))
    else:
        await callback.message.answer(
            "👋 Введи свой баркод (13 цифр):"
        )
        await state.set_state(StudentVerificationState.AWAITING_BARCODE)


@router.message(StudentVerificationState.AWAITING_BARCODE)
async def register_by_barcode(message: Message, state: FSMContext):
    barcode = message.text.strip() if message.text else ""
    if not barcode.isdigit() or len(barcode) != 13:
        return await message.answer("❗ Баркод должен содержать ровно 13 цифр")

    user_id = message.from_user.id

    with Session() as session:
        student = session.query(Student).filter_by(barcode=barcode).first()
        if not student:
            return await message.answer(
                "❌ Студент с таким баркодом не найден.\n\nОбратись в Профком: 📍 И-108",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🆘 Поддержка", callback_data="support_unreg")]
                ])
            )

        # ЗАЩИТА: если баркод уже привязан к ДРУГОМУ пользователю — блокируем
        if student.telegram_id and student.telegram_id != user_id:
            return await message.answer(
                "⚠️ Этот баркод уже привязан к другому аккаунту.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🆘 Поддержка", callback_data="support_unreg")]
                ])
            )

        # Привязываем только если telegram_id ещё не задан
        if not student.telegram_id:
            student.telegram_id = user_id
            session.commit()

    await state.clear()
    is_admin = user_id in ADMIN_IDS
    await message.answer("✅ Готово! Ты успешно зарегистрирован.")
    await message.answer("🏠 Главное меню:", reply_markup=main_menu_keyboard(is_admin))
