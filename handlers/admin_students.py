# handlers/admin_students.py
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from sqlalchemy import text

from models import Student
from database import Session
from states import StudentSearchState, StudentEditState
from config import ADMIN_IDS

router = Router()


# ── Панель студентов (только для админов) ───────────────────────────────────
@router.callback_query(F.data == "students")
async def open_student_panel(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав")

    await callback.message.edit_text(
        "👥 Панель студентов:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Найти студента", callback_data="find_student")],
            [InlineKeyboardButton(text="⬅️ Назад",          callback_data="menu_back")],
        ])
    )


# ── Поиск студента ──────────────────────────────────────────────────────────
@router.callback_query(F.data == "find_student")
async def prompt_search(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("🔎 Введите ФИО или баркод студента:")
    await state.set_state(StudentSearchState.AWAITING_INPUT)


@router.message(StudentSearchState.AWAITING_INPUT)
async def search_student(message: Message, state: FSMContext):
    query = message.text.strip()
    with Session() as session:
        results = session.execute(text("""
            SELECT id, full_name, barcode, faculty, balance
            FROM students
            WHERE full_name ILIKE :q OR barcode = :exact
            LIMIT 5
        """), {"q": f"%{query}%", "exact": query}).fetchall()

    await state.clear()

    if not results:
        return await message.answer("❌ Студенты не найдены.")

    # Правильный способ построить клавиатуру в aiogram 3
    buttons = [
        [InlineKeyboardButton(
            text=f"{row[1]} ({row[2]})",
            callback_data=f"edit_student_{row[0]}"
        )]
        for row in results
    ]
    await message.answer(
        "📋 Найденные студенты:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


# ── Редактирование студента ─────────────────────────────────────────────────
@router.callback_query(F.data.startswith("edit_student_"))
async def edit_student_prompt(callback: CallbackQuery, state: FSMContext):
    student_id = int(callback.data.split("_")[-1])

    with Session() as session:
        student = session.query(Student).get(student_id)
        if not student:
            return await callback.answer("Студент не найден")

        info = (
            f"👤 {student.full_name}\n"
            f"Баркод: {student.barcode}\n"
            f"Факультет: {student.faculty}\n"
            f"Баллы: {student.balance}\n"
            f"Роль: {student.role}\n"
            f"Статус: {student.status}"
        )

    await state.update_data(student_id=student_id)
    await callback.message.answer(
        f"{info}\n\n✏️ Какое поле изменить?\nФИО / Факультет / Баллы / Статус / Роль"
    )
    await state.set_state(StudentEditState.AWAITING_FIELD)


@router.message(StudentEditState.AWAITING_FIELD)
async def get_field_value(message: Message, state: FSMContext):
    field_map = {
        "фио": "full_name",
        "факультет": "faculty",
        "баллы": "balance",
        "статус": "status",
        "роль": "role",
    }
    field_key = message.text.strip().lower()
    if field_key not in field_map:
        return await message.answer("❌ Допустимые поля: ФИО, Факультет, Баллы, Статус, Роль")

    await state.update_data(field=field_map[field_key])
    await state.set_state(StudentEditState.AWAITING_VALUE)
    await message.answer("✏️ Введите новое значение:")


@router.message(StudentEditState.AWAITING_VALUE)
async def save_field(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data["field"]
    value = message.text.strip()
    student_id = data["student_id"]

    with Session() as session:
        student = session.query(Student).get(student_id)
        if not student:
            await state.clear()
            return await message.answer("❌ Студент не найден.")

        if field == "balance":
            try:
                value = int(value)
            except ValueError:
                return await message.answer("❗ Баллы должны быть числом.")

        if field == "status" and value not in ("active", "blocked"):
            return await message.answer("❗ Статус: active или blocked")
        if field == "role" and value not in ("student", "moderator", "admin"):
            return await message.answer("❗ Роль: student, moderator или admin")

        setattr(student, field, value)
        session.commit()

    await state.clear()
    await message.answer("✅ Изменения сохранены.")
