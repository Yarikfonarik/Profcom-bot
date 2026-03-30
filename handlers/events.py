# handlers/events.py
import os
import pandas as pd

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from database import Session
from models import Event, Attendance, Student, UnmatchedBarcode
from states import EventUploadState, ManualBarcodeState
from config import ADMIN_IDS

router = Router()


# ── Меню мероприятий ────────────────────────────────────────────────────────
@router.callback_query(F.data == "menu_events")
async def show_event_menu(callback: CallbackQuery):
    is_admin = callback.from_user.id in ADMIN_IDS
    buttons = []
    if is_admin:
        buttons.append([InlineKeyboardButton(text="➕ Добавить мероприятие", callback_data="add_event")])
        buttons.append([InlineKeyboardButton(text="✍️ Ввести баркод вручную", callback_data="add_manual_barcode")])

    with Session() as session:
        events = session.query(Event).order_by(Event.created_at.desc()).limit(10).all()

    if events:
        buttons.append([InlineKeyboardButton(text="📋 Мои посещения", callback_data="my_events")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_back")])

    await callback.message.edit_text(
        "📥 Меню мероприятий:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


# ── Мои посещения ───────────────────────────────────────────────────────────
@router.callback_query(F.data == "my_events")
async def show_my_events(callback: CallbackQuery):
    user_id = callback.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        if not student:
            return await callback.answer("❌ Ты не зарегистрирован.", show_alert=True)

        attendances = (
            session.query(Attendance)
            .filter_by(student_id=student.id)
            .join(Event)
            .order_by(Attendance.scanned_at.desc())
            .limit(10)
            .all()
        )

    if not attendances:
        msg = "📥 Ты ещё не посещал мероприятий."
    else:
        lines = [f"• {a.event.title} — +{a.event.points} баллов" for a in attendances]
        msg = "📥 Твои последние посещения:\n\n" + "\n".join(lines)

    await callback.message.answer(
        msg,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_events")]
        ])
    )


# ── Добавление мероприятия (CSV/Excel) ──────────────────────────────────────
@router.callback_query(F.data == "add_event")
async def begin_event_upload(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав")
    await state.set_state(EventUploadState.AWAITING_TITLE)
    await callback.message.answer("📌 Введите название мероприятия:")


@router.message(EventUploadState.AWAITING_TITLE)
async def get_event_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(EventUploadState.AWAITING_POINTS)
    await message.answer("💰 Сколько баллов начислять за участие?")


@router.message(EventUploadState.AWAITING_POINTS)
async def get_event_points(message: Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("❗ Введите целое число")
    await state.update_data(points=int(message.text.strip()))
    await state.set_state(EventUploadState.AWAITING_FILE)
    await message.answer("📎 Отправьте CSV или Excel-файл со списком штрихкодов (первый столбец):")


@router.message(EventUploadState.AWAITING_FILE)
async def process_event_file(message: Message, state: FSMContext, bot: Bot):
    if not message.document:
        return await message.answer("❗ Отправьте файл (.xlsx, .xls или .csv)")

    file = message.document
    ext = file.file_name.rsplit(".", 1)[-1].lower()
    if ext not in ("xlsx", "xls", "csv"):
        return await message.answer("❗ Поддерживаются только форматы .xlsx, .xls, .csv")

    path = f"media/uploads/{file.file_name}"
    os.makedirs("media/uploads", exist_ok=True)

    # Правильный способ скачивания файлов в aiogram 3
    await bot.download(file.file_id, destination=path)

    data = await state.get_data()
    title = data["title"]
    points = data["points"]

    try:
        if ext == "csv":
            df = pd.read_csv(path, dtype=str)
        else:
            df = pd.read_excel(path, dtype=str)
    except Exception as e:
        await state.clear()
        return await message.answer(f"❌ Не удалось прочитать файл: {e}")

    barcodes = df.iloc[:, 0].str.strip().dropna().tolist()

    found = 0
    not_found = []

    with Session() as session:
        event = Event(title=title, points=points)
        session.add(event)
        session.flush()  # чтобы получить event.id до commit

        for code in barcodes:
            student = session.query(Student).filter_by(barcode=code).first()
            if student:
                student.balance += points
                session.add(Attendance(student_id=student.id, event_id=event.id))
                found += 1
            else:
                session.add(UnmatchedBarcode(barcode=code, event_id=event.id))
                not_found.append(code)

        session.commit()
        event_title = event.title

    msg = (
        f"📊 Отчёт: {event_title}\n\n"
        f"👥 Найдено студентов: {found}\n"
        f"❌ Не найдено: {len(not_found)}"
    )
    if not_found:
        preview = "\n".join(not_found[:10])
        msg += f"\n\n📍 Неизвестные штрихкоды:\n{preview}"
        if len(not_found) > 10:
            msg += f"\n...и ещё {len(not_found) - 10}"

    await state.clear()
    await message.answer(msg)


# ── Ручной ввод баркода ─────────────────────────────────────────────────────
@router.callback_query(F.data == "add_manual_barcode")
async def begin_manual_barcode(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав")
    await state.set_state(ManualBarcodeState.AWAITING_EVENT_ID)
    await callback.message.answer("🔢 Введите ID мероприятия:")


@router.message(ManualBarcodeState.AWAITING_EVENT_ID)
async def get_event_id(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        return await message.answer("❗ Введите число")
    event_id = int(message.text.strip())

    with Session() as session:
        event = session.query(Event).get(event_id)
        if not event:
            return await message.answer("❌ Мероприятие не найдено.")

    await state.update_data(event_id=event_id)
    await state.set_state(ManualBarcodeState.AWAITING_BARCODE)
    await message.answer("📥 Введите штрихкод студента:")


@router.message(ManualBarcodeState.AWAITING_BARCODE)
async def add_manual_barcode(message: Message, state: FSMContext):
    data = await state.get_data()
    event_id = data["event_id"]
    barcode = message.text.strip()

    with Session() as session:
        student = session.query(Student).filter_by(barcode=barcode).first()
        event = session.query(Event).get(event_id)

        if not student:
            return await message.answer("❌ Студент с таким баркодом не найден.")
        if not event:
            return await message.answer("❌ Мероприятие не найдено.")

        student.balance += event.points
        session.add(Attendance(student_id=student.id, event_id=event_id))
        # Убираем из нераспознанных если был там
        session.query(UnmatchedBarcode).filter_by(
            barcode=barcode, event_id=event_id
        ).delete()
        session.commit()

    await state.clear()
    await message.answer(f"✅ Баркод добавлен. Студенту начислено {event.points} баллов.")
