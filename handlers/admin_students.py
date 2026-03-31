# handlers/admin_students.py
import io
import pandas as pd

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from sqlalchemy import text

from models import Student
from database import Session
from states import StudentSearchState, StudentEditState, ImportState
from config import ADMIN_IDS

router = Router()


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


@router.callback_query(F.data == "find_student")
async def prompt_search(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("🔎 Введите ФИО, баркод или факультет:")
    await state.set_state(StudentSearchState.AWAITING_INPUT)


# Строго по состоянию — не перехватывает чужие сообщения
@router.message(StudentSearchState.AWAITING_INPUT)
async def search_student(message: Message, state: FSMContext):
    query = message.text.strip()
    await state.clear()

    with Session() as session:
        rows = session.execute(text("""
            SELECT id, full_name, barcode, faculty, balance
            FROM students
            WHERE full_name ILIKE :q OR barcode ILIKE :q OR faculty ILIKE :q
            ORDER BY full_name
            LIMIT 20
        """), {"q": f"%{query}%"}).fetchall()

    if not rows:
        return await message.answer(
            "❌ Студенты не найдены.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔍 Снова", callback_data="find_student")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="students")],
            ])
        )

    count_txt = f"Найдено: {len(rows)}" + (" (первые 20)" if len(rows) == 20 else "")
    buttons = [
        [InlineKeyboardButton(text=f"{r[1]} | {r[2]}", callback_data=f"stucard_{r[0]}")]
        for r in rows
    ]
    buttons.append([InlineKeyboardButton(text="🔍 Новый поиск", callback_data="find_student")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад",       callback_data="students")])

    await message.answer(
        f"📋 {count_txt}:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data.startswith("stucard_"))
async def show_student_card(callback: CallbackQuery, state: FSMContext):
    student_id = int(callback.data.split("_")[1])

    with Session() as session:
        s = session.query(Student).get(student_id)
        if not s:
            return await callback.answer("Студент не найден", show_alert=True)

        status_icon = "✅" if s.status == "active" else "⛔"
        role_icon = {"student": "🎓", "moderator": "🛡", "admin": "👑"}.get(s.role, "🎓")
        tg = str(s.telegram_id) if s.telegram_id else "не привязан"

        msg = (
            f"👤 *{s.full_name}*\n\n"
            f"🔢 Баркод: `{s.barcode}`\n"
            f"🏛 Факультет: {s.faculty or '—'}\n"
            f"💰 Баллы: *{s.balance}*\n"
            f"{role_icon} Роль: {s.role}\n"
            f"{status_icon} Статус: {s.status}\n"
            f"📱 Telegram ID: {tg}"
        )

    await state.update_data(student_id=student_id)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 Баллы",     callback_data=f"sf_{student_id}_balance"),
            InlineKeyboardButton(text="🏛 Факультет", callback_data=f"sf_{student_id}_faculty"),
        ],
        [
            InlineKeyboardButton(text="🎓 Роль",      callback_data=f"sf_{student_id}_role"),
            InlineKeyboardButton(text="🔒 Статус",    callback_data=f"sf_{student_id}_status"),
        ],
        [InlineKeyboardButton(text="📝 ФИО",          callback_data=f"sf_{student_id}_full_name")],
        [InlineKeyboardButton(text="⬅️ К списку",     callback_data="find_student")],
    ])

    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=kb)


@router.callback_query(F.data.startswith("sf_"))
async def quick_edit_field(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_", 2)
    student_id = int(parts[1])
    field = parts[2]

    prompts = {
        "balance":   "💰 Введите новые баллы (500, +100 или -50):",
        "faculty":   "🏛 Введите факультет:",
        "role":      "🎓 Роль: student / moderator / admin",
        "status":    "🔒 Статус: active / blocked",
        "full_name": "📝 Введите ФИО:",
    }

    await state.update_data(student_id=student_id, field=field)
    await state.set_state(StudentEditState.AWAITING_VALUE)
    await callback.message.answer(prompts.get(field, "Введите значение:"))


# Строго по состоянию
@router.message(StudentEditState.AWAITING_VALUE)
async def save_student_field(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data["field"]
    value = message.text.strip()
    student_id = data["student_id"]

    with Session() as session:
        s = session.query(Student).get(student_id)
        if not s:
            await state.clear()
            return await message.answer("❌ Студент не найден.")

        if field == "balance":
            try:
                if value.startswith("+"):
                    s.balance += int(value[1:])
                elif value.startswith("-"):
                    s.balance -= int(value[1:])
                else:
                    s.balance = int(value)
            except ValueError:
                return await message.answer("❗ Введите число (500, +100, -50)")
        elif field == "status":
            if value not in ("active", "blocked"):
                return await message.answer("❗ active или blocked")
            s.status = value
        elif field == "role":
            if value not in ("student", "moderator", "admin"):
                return await message.answer("❗ student / moderator / admin")
            s.role = value
        else:
            setattr(s, field, value)

        session.commit()

    await state.clear()
    await message.answer("✅ Сохранено!")

    # Показываем обновлённую карточку через fake callback
    class FakeCb:
        data = f"stucard_{student_id}"
        from_user = message.from_user
        class _msg:
            async def delete(self): pass
            answer = message.answer
        message = _msg()
        async def answer(self, *a, **kw): pass

    await show_student_card(FakeCb(), state)


# ── Импорт из Excel (строго по состоянию) ────────────────────────────────────
@router.callback_query(F.data == "import_students")
async def import_students_prompt(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав")
    await callback.message.answer(
        "📥 Отправьте .xlsx файл.\n\n"
        "Колонки: Фамилия, Имя, Отчество, Факультет/Институт, barcode, Статус"
    )
    await state.set_state(ImportState.AWAITING_FILE)


@router.message(ImportState.AWAITING_FILE, F.document)
async def process_import_excel(message: Message, state: FSMContext, bot: Bot):
    if message.from_user.id not in ADMIN_IDS:
        return
    if not message.document.file_name.endswith(".xlsx"):
        return await message.answer("❗ Только .xlsx")

    await message.answer("⏳ Обрабатываю...")

    try:
        file = await bot.get_file(message.document.file_id)
        file_bytes = await bot.download_file(file.file_path)
        df = pd.read_excel(io.BytesIO(file_bytes.read()), dtype=str)
        df.columns = df.columns.str.strip()

        added = updated = errors = 0

        with Session() as session:
            for _, row in df.iterrows():
                try:
                    barcode = str(row.get("barcode", "") or "").strip()
                    if not barcode or barcode == "nan":
                        continue
                    parts = [str(row.get(c, "") or "").strip() for c in ("Фамилия", "Имя", "Отчество")]
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
                        session.add(Student(full_name=full_name, barcode=barcode, faculty=faculty, status=status))
                        added += 1
                except Exception:
                    errors += 1
            session.commit()

        await state.clear()
        await message.answer(f"✅ Готово!\n\n➕ Добавлено: {added}\n🔄 Обновлено: {updated}\n❌ Ошибок: {errors}")

    except Exception as e:
        await state.clear()
        await message.answer(f"❌ Ошибка: {e}")
