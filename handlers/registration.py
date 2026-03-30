# handlers/registration.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import text

from models import Student
from states import StudentVerificationState
from database import Session
from config import ADMIN_IDS
from keyboards import main_menu_keyboard   # единственный источник — keyboards.py

router = Router()


# ── /start ─────────────────────────────────────────────────────────────────
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Начать", callback_data="begin_register")]
    ])
    await message.answer("Добро пожаловать! Нажми кнопку ниже, чтобы начать:", reply_markup=kb)


# ── Кнопка «Начать» ────────────────────────────────────────────────────────
@router.callback_query(F.data == "begin_register")
async def handle_start(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()

    if student:
        is_admin = user_id in ADMIN_IDS
        await callback.message.answer(
            "✅ Ты уже зарегистрирован. Открываю меню...",
            reply_markup=main_menu_keyboard(is_admin)
        )
    else:
        await callback.message.answer(
            "👋 Привет!\n\nВведи свой баркод\n(13 цифр без пробелов)\n\nПример: 2004111111111"
        )
        await state.set_state(StudentVerificationState.AWAITING_BARCODE)


# ── Ввод баркода ───────────────────────────────────────────────────────────
@router.message(StudentVerificationState.AWAITING_BARCODE)
async def register_by_barcode(message: Message, state: FSMContext):
    barcode = message.text.strip()
    if not barcode.isdigit() or len(barcode) != 13:
        return await message.answer("❗ Баркод должен содержать ровно 13 цифр без пробелов")

    with Session() as session:
        student = session.query(Student).filter_by(barcode=barcode).first()

        if not student:
            return await message.answer(
                "❌ Не удалось найти студента с таким баркодом.\n\n"
                "Если ты уверен, что всё правильно — обратись в Профком:\n"
                "📍 И-108\n"
                "📲 https://vk.com/profkom21?from=groups"
            )

        if student.telegram_id and student.telegram_id != message.from_user.id:
            return await message.answer(
                "⚠️ Этот баркод уже зарегистрирован другим пользователем.\n\n"
                "Если это ошибка — обратись в Профком:\n"
                "📍 И-108\n"
                "📲 https://vk.com/profkom21?from=groups"
            )

        student.telegram_id = message.from_user.id
        session.commit()

    await state.clear()
    is_admin = message.from_user.id in ADMIN_IDS
    await message.answer("✅ Готово! Ты успешно зарегистрирован.")
    await message.answer("📋 Главное меню:", reply_markup=main_menu_keyboard(is_admin))


# ── Профиль ────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "menu_profile")
async def open_profile(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        if not student:
            return await callback.message.answer("❌ Ты не зарегистрирован.")
        rank = session.execute(
            text("SELECT RANK() OVER (ORDER BY balance DESC) FROM students WHERE id = :id"),
            {"id": student.id}
        ).scalar()

        status = "✅ Активен" if student.status == "active" else "⛔ Заблокирован"
        msg = (
            f"👤 Профиль\n"
            f"ФИО: {student.full_name}\n"
            f"Баллы: {student.balance}\n"
            f"Место в рейтинге: #{rank}\n"
            f"Факультет: {student.faculty}\n"
            f"Статус: {status}"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔁 Перерегистрация", callback_data="begin_register")],
        [InlineKeyboardButton(text="🏠 Главное меню",    callback_data="menu_back")],
    ])
    try:
        await callback.message.edit_text(msg, reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
