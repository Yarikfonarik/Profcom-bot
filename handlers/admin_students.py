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
            [InlineKeyboardButton(text="🔍 Найти студента",  callback_data="find_student")],
            [InlineKeyboardButton(text="📥 Импорт из Excel", callback_data="import_students")],
            [InlineKeyboardButton(text="⬅️ Назад",          callback_data="admin_panel")],
        ])
    )


# ── Поиск студента ──────────────────────────────────────────────────────────
@router.callback_query(F.data == "find_student")
async def prompt_search(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "🔎 Введите ФИО (или часть), баркод или факультет для поиска:\n\n"
        "Например: «Иванов» или «2004» или «ИТ»"
    )
    await state.set_state(StudentSearchState.AWAITING_INPUT)


@router.message(StudentSearchState.AWAITING_INPUT)
async def search_student(message: Message, state: FSMContext):
    query = message.text.strip()
    await state.clear()

    with Session() as session:
        results = session.execute(text("""
            SELECT id, full_name, barcode, faculty, balance, role, status, telegram_id
            FROM students
            WHERE full_name ILIKE :q
               OR barcode ILIKE :q
               OR faculty ILIKE :q
            ORDER BY full_name
            LIMIT 20
        """), {"q": f"%{query}%"}).fetchall()

    if not results:
        return await message.answer(
            "❌ Студенты не найдены.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔍 Искать снова", callback_data="find_student")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="students")],
            ])
        )

    # Показываем количество найденных
    header = f"📋 Найдено: {len(results)} студентов{' (показаны первые 20)' if len(results) == 20 else ''}:\n"
    await message.answer(header)

    # Выводим кнопки по одной на строку
    buttons = [
        [InlineKeyboardButton(
            text=f"{row[1]} | {row[2]}",
            callback_data=f"edit_student_{row[0]}"
        )]
        for row in results
    ]
    buttons.append([InlineKeyboardButton(text="🔍 Новый поиск", callback_data="find_student")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="students")])

    await message.answer(
        "Нажми на студента чтобы посмотреть и редактировать:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


# ── Просмотр и редактирование студента ─────────────────────────────────────
@router.callback_query(F.data.startswith("edit_student_"))
async def show_student(callback: CallbackQuery, state: FSMContext):
    student_id = int(callback.data.split("_")[-1])

    with Session() as session:
        student = session.query(Student).get(student_id)
        if not student:
            return await callback.answer("Студент не найден")

        status_icon = "✅" if student.status == "active" else "⛔"
        role_icon = {"student": "🎓", "moderator": "🛡", "admin": "👑"}.get(student.role, "🎓")
        tg = f"@{student.telegram_id}" if student.telegram_id else "не привязан"

        msg = (
            f"👤 *{student.full_name}*\n\n"
            f"🔢 Баркод: `{student.barcode}`\n"
            f"🏛 Факультет: {student.faculty or '—'}\n"
            f"💰 Баллы: *{student.balance}*\n"
            f"{role_icon} Роль: {student.role}\n"
            f"{status_icon} Статус: {student.status}\n"
            f"📱 Telegram: {tg}"
        )

    await state.update_data(student_id=student_id)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 Изменить баллы",    callback_data=f"sedit_{student_id}_balance"),
            InlineKeyboardButton(text="🏛 Факультет",         callback_data=f"sedit_{student_id}_faculty"),
        ],
        [
            InlineKeyboardButton(text="🎓 Роль",              callback_data=f"sedit_{student_id}_role"),
            InlineKeyboardButton(text="🔒 Статус",            callback_data=f"sedit_{student_id}_status"),
        ],
        [
            InlineKeyboardButton(text="📝 ФИО",               callback_data=f"sedit_{student_id}_full_name"),
        ],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="find_student")],
    ])

    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=kb)


# ── Быстрое редактирование поля ────────────────────────────────────────────
@router.callback_query(F.data.startswith("sedit_"))
async def quick_edit_field(callback: CallbackQuery, state: FSMContext):
    # sedit_{student_id}_{field}
    parts = callback.data.split("_", 2)
    student_id = int(parts[1])
    field = parts[2]

    prompts = {
        "balance":   "💰 Введите новое количество баллов (число):\n\nМожно указать +100 или -50 для изменения:",
        "faculty":   "🏛 Введите новый факультет:",
        "role":      "🎓 Введите роль:\n• student\n• moderator\n• admin",
        "status":    "🔒 Введите статус:\n• active\n• blocked",
        "full_name": "📝 Введите новое ФИО:",
    }

    await state.update_data(student_id=student_id, field=field)
    await state.set_state(StudentEditState.AWAITING_VALUE)
    await callback.message.answer(prompts.get(field, "Введите новое значение:"))


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
            # Поддержка +100 / -50 / просто числа
            try:
                if value.startswith("+"):
                    student.balance += int(value[1:])
                elif value.startswith("-"):
                    student.balance -= int(value[1:])
                else:
                    student.balance = int(value)
            except ValueError:
                return await message.answer("❗ Введите число (например: 100, +50, -20)")

        elif field == "status":
            if value not in ("active", "blocked"):
                return await message.answer("❗ Статус: active или blocked")
            student.status = value

        elif field == "role":
            if value not in ("student", "moderator", "admin"):
                return await message.answer("❗ Роль: student, moderator или admin")
            student.role = value

        else:
            setattr(student, field, value)

        session.commit()
        student_id_saved = student.id

    await state.clear()
    await message.answer("✅ Изменения сохранены!")

    # Показываем обновлённую карточку студента
    class FakeCallback:
        def __init__(self, msg, sid):
            self.message = msg
            self.data = f"edit_student_{sid}"
        async def answer(self, *a, **kw): pass
        from_user = message.from_user

    fake = FakeCallback(message, student_id_saved)
    await show_student(fake, state)


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


@router.message(F.document)
async def process_import_excel(message: Message, state: FSMContext, bot: Bot):
    current_state = await state.get_state()
    if current_state != "import_excel":
        return
    if message.from_user.id not in ADMIN_IDS:
        return
    if not message.document.file_name.endswith(".xlsx"):
        return await message.answer("❗ Поддерживается только .xlsx формат")

    await message.answer("⏳ Обрабатываю файл...")

    try:
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
                    barcode = str(row.get("barcode", "") or "").strip()
                    if not barcode or barcode == "nan":
                        continue

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
                        session.add(Student(
                            full_name=full_name, barcode=barcode,
                            faculty=faculty, status=status,
                        ))
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
