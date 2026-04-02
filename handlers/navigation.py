# handlers/admin_students.py
import io
import pandas as pd

from aiogram import Router, F, Bot
from aiogram.types import (
    CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup, BufferedInputFile
)
from aiogram.fsm.context import FSMContext
from sqlalchemy import text

from models import Student
from database import Session
from states import StudentSearchState, StudentEditState, ImportState, AdminMsgState
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


@router.message(StudentSearchState.AWAITING_INPUT)
async def search_student(message: Message, state: FSMContext):
    query = " ".join(message.text.strip().split())
    await state.clear()

    with Session() as session:
        rows = session.execute(text("""
            SELECT id, full_name, barcode, faculty, balance
            FROM students
            WHERE full_name ILIKE :q OR barcode ILIKE :q OR faculty ILIKE :q
            ORDER BY full_name LIMIT 20
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
    await message.answer(f"📋 {count_txt}:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("stucard_"))
async def show_student_card(callback: CallbackQuery, state: FSMContext, bot: Bot):
    student_id = int(callback.data.split("_")[1])

    with Session() as session:
        s = session.query(Student).get(student_id)
        if not s:
            return await callback.answer("Студент не найден", show_alert=True)

        role_icon = {"student": "🎓", "moderator": "🛡", "admin": "👑"}.get(s.role, "🎓")
        tg = str(s.telegram_id) if s.telegram_id else "не привязан"

        caption = (
            f"👤 {s.full_name}\n"
            f"🔢 Баркод: {s.barcode}\n"
            f"🏛 Факультет: {s.faculty or '—'}\n\n"
            f"💰 Баллы: {s.balance}\n"
            f"{role_icon} Роль: {s.role}\n"
            f"{'✅' if s.status == 'active' else '⛔'} Статус: {s.status}\n"
            f"📱 Telegram ID: {tg}"
        )

        barcode    = s.barcode
        qr_file_id = s.qr_file_id

    await state.update_data(student_id=student_id)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 Баллы",       callback_data=f"sf_{student_id}_balance"),
            InlineKeyboardButton(text="🔄 Обнулить",    callback_data=f"sreset_{student_id}"),
        ],
        [
            InlineKeyboardButton(text="🏛 Факультет",   callback_data=f"sf_{student_id}_faculty"),
            InlineKeyboardButton(text="🎓 Роль",        callback_data=f"sf_{student_id}_role"),
        ],
        [
            InlineKeyboardButton(text="🔒 Статус",      callback_data=f"sf_{student_id}_status"),
            InlineKeyboardButton(text="📝 ФИО",         callback_data=f"sf_{student_id}_full_name"),
        ],
        [InlineKeyboardButton(text="💬 Написать",       callback_data=f"smsg_{student_id}")],
        [
            InlineKeyboardButton(text="🔍 Найти ещё",   callback_data="find_student"),
            InlineKeyboardButton(text="🏠 Админ панель", callback_data="admin_panel"),
        ],
    ])

    try:
        await callback.message.delete()
    except Exception:
        pass

    # Показываем карточку с QR
    if qr_file_id:
        try:
            await callback.message.answer_photo(photo=qr_file_id, caption=caption, reply_markup=kb)
            return
        except Exception:
            # Сбрасываем устаревший file_id
            with Session() as session:
                st = session.query(Student).get(student_id)
                if st:
                    st.qr_file_id = None
                    session.commit()

    # Генерируем QR
    if barcode:
        try:
            from qr_generator import generate_qr_bytes
            qr_bytes = generate_qr_bytes(barcode)
            file = BufferedInputFile(qr_bytes, filename=f"qr_{barcode}.png")
            msg = await callback.message.answer_photo(photo=file, caption=caption, reply_markup=kb)

            new_file_id = msg.photo[-1].file_id
            with Session() as session:
                st = session.query(Student).get(student_id)
                if st:
                    st.qr_file_id = new_file_id
                    session.commit()
            return
        except Exception:
            pass

    # Если QR не удалось — без фото
    await callback.message.answer(caption, reply_markup=kb)


# ── Обнуление баллов одного студента ────────────────────────────────────────
@router.callback_query(F.data.startswith("sreset_"))
async def reset_one_balance(callback: CallbackQuery, state: FSMContext, bot: Bot):
    student_id = int(callback.data.split("_")[1])
    with Session() as session:
        s = session.query(Student).get(student_id)
        if s:
            s.balance = 0
            session.commit()
    await callback.answer("✅ Баллы обнулены")
    callback.data = f"stucard_{student_id}"
    await show_student_card(callback, state, bot)


# ── Редактирование поля ──────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("sf_"))
async def quick_edit_field(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_", 2)
    student_id = int(parts[1])
    field = parts[2]

    prompts = {
        "balance":   "💰 Введите баллы (500, +100 или -50):",
        "faculty":   "🏛 Введите факультет:",
        "role":      "🎓 Роль: student / moderator / admin",
        "status":    "🔒 Статус: active / blocked",
        "full_name": "📝 Введите ФИО:",
    }

    await state.update_data(student_id=student_id, field=field)
    await state.set_state(StudentEditState.AWAITING_VALUE)
    await callback.message.answer(prompts.get(field, "Введите значение:"))


@router.message(StudentEditState.AWAITING_VALUE)
async def save_student_field(message: Message, state: FSMContext, bot: Bot):
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
                return await message.answer("❗ Введите число")
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

    class FakeCb:
        data = f"stucard_{student_id}"
        from_user = message.from_user
        class _msg:
            async def delete(self): pass
            answer = message.answer
            answer_photo = message.answer
        message = _msg()
        async def answer(self, *a, **kw): pass

    await show_student_card(FakeCb(), state, bot)


# ── Написать студенту ────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("smsg_"))
async def msg_student_prompt(callback: CallbackQuery, state: FSMContext):
    student_id = int(callback.data.split("_")[1])
    await state.update_data(msg_student_id=student_id)
    await state.set_state(AdminMsgState.AWAITING_MESSAGE)
    await callback.message.answer(
        "💬 Введите сообщение для студента (текст или фото):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"stucard_{student_id}")]
        ])
    )


@router.message(AdminMsgState.AWAITING_MESSAGE)
async def send_msg_to_student(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    student_id = data.get("msg_student_id")
    await state.clear()

    with Session() as session:
        s = session.query(Student).get(student_id)
        if not s or not s.telegram_id:
            return await message.answer("❌ У студента нет Telegram.")
        target_id = s.telegram_id
        student_name = s.full_name

    mod_name = message.from_user.full_name or "Администрация"
    header = f"📩 *Сообщение от администрации ({mod_name}):*\n\n"

    reply_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Ответить", callback_data="support")]
    ])

    try:
        if message.text:
            await bot.send_message(target_id, header + message.text, parse_mode="Markdown", reply_markup=reply_kb)
        elif message.photo:
            await bot.send_photo(target_id, message.photo[-1].file_id,
                caption=header + (message.caption or ""), parse_mode="Markdown", reply_markup=reply_kb)
        elif message.document:
            await bot.send_document(target_id, message.document.file_id,
                caption=header + (message.caption or ""), parse_mode="Markdown", reply_markup=reply_kb)
        await message.answer(f"✅ Отправлено {student_name}!")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


# ── Импорт из Excel ──────────────────────────────────────────────────────────
@router.callback_query(F.data == "import_students")
async def import_students_prompt(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав")
    await callback.message.answer("📥 Отправьте .xlsx файл.")
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
        await message.answer(f"✅ Готово!\n➕ {added} | 🔄 {updated} | ❌ {errors}")
    except Exception as e:
        await state.clear()
        await message.answer(f"❌ Ошибка: {e}")
