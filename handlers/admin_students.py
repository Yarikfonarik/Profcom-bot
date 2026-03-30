# handlers/admin_students.py
import io
import pandas as pd

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from sqlalchemy import text

from models import Student
from database import Session
from states import StudentSearchState, StudentEditState
from config import ADMIN_IDS

router = Router()


# ── Панель студентов ────────────────────────────────────────────────────────
@router.callback_query(F.data == "students")
async def open_student_panel(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав")

    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer(
        "👥 Панель студентов:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Найти студента",       callback_data="find_student")],
            [InlineKeyboardButton(text="📥 Импорт из Excel",      callback_data="import_students")],
            [InlineKeyboardButton(text="⬅️ Назад",               callback_data="admin_panel")],
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


# ── Импорт студентов из Excel ───────────────────────────────────────────────
@router.callback_query(F.data == "import_students")
async def import_students_prompt(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав")

    await callback.message.answer(
        "📥 Отправьте Excel файл (.xlsx) со студентами.\n\n"
        "Ожидаемые колонки: Фамилия, Имя, Отчество, Факультет/Институт, barcode, Статус\n\n"
        "⚠️ Новые студенты будут добавлены, существующие (по баркоду) — обновлены."
    )
    await state.set_state("import_excel")


@router.message(F.document, F.document.file_name.endswith(".xlsx"))
async def process_import_excel(message: Message, state: FSMContext, bot: Bot):
    current_state = await state.get_state()
    if current_state != "import_excel":
        return

    if message.from_user.id not in ADMIN_IDS:
        return

    await message.answer("⏳ Обрабатываю файл...")

    try:
        # Скачиваем файл в память
        file = await bot.get_file(message.document.file_id)
        file_bytes = await bot.download_file(file.file_path)
        content = file_bytes.read()

        df = pd.read_excel(io.BytesIO(content), dtype=str)
        df.columns = df.columns.str.strip()

        added = 0
        updated = 0
        errors = 0

        with Session() as session:
            for _, row in df.iterrows():
                try:
                    barcode = str(row.get("barcode", "")).strip()
                    if not barcode or barcode == "nan":
                        continue

                    # Собираем ФИО
                    parts = [
                        str(row.get("Фамилия", "") or "").strip(),
                        str(row.get("Имя", "") or "").strip(),
                        str(row.get("Отчество", "") or "").strip(),
                    ]
                    full_name = " ".join(p for p in parts if p and p != "nan")

                    faculty = str(row.get("Факультет/Институт", "") or "").strip()
                    if faculty == "nan":
                        faculty = ""

                    status = str(row.get("Статус", "active") or "active").strip()
                    if status not in ("active", "blocked"):
                        status = "active"

                    existing = session.query(Student).filter_by(barcode=barcode).first()

                    if existing:
                        existing.full_name = full_name
                        existing.faculty = faculty
                        existing.status = status
                        updated += 1
                    else:
                        new_student = Student(
                            full_name=full_name,
                            barcode=barcode,
                            faculty=faculty,
                            status=status,
                        )
                        session.add(new_student)
                        added += 1

                except Exception:
                    errors += 1

            session.commit()

        await state.clear()
        await message.answer(
            f"✅ Импорт завершён!\n\n"
            f"➕ Добавлено: {added}\n"
            f"🔄 Обновлено: {updated}\n"
            f"❌ Ошибок: {errors}"
        )

    except Exception as e:
        await state.clear()
        await message.answer(f"❌ Ошибка при обработке файла: {e}")
