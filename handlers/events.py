import os
import pandas as pd
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from datetime import datetime

from database import Session
from models import Event, Attendance, Student, UnmatchedBarcode
from states import EventUploadState, ManualBarcodeState

router = Router()

@router.callback_query(F.data == "menu_events")
async def show_event_menu(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить мероприятие", callback_data="add_event")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_back")]
    ])
    await callback.message.edit_text("📥 Мероприятия:", reply_markup=kb)

@router.callback_query(F.data == "add_event")
async def begin_event_upload(callback: CallbackQuery, state: FSMContext):
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
    await message.answer("📎 Отправьте CSV/Excel-файл со списком штрихкодов:")

@router.message(EventUploadState.AWAITING_FILE)
async def process_event_file(message: Message, state: FSMContext):
    if not message.document:
        return await message.answer("❗ Отправьте файл в формате Excel или CSV")

    file = message.document
    ext = file.file_name.split(".")[-1]
    if ext not in ["xlsx", "xls", "csv"]:
        return await message.answer("❗ Поддерживаются только форматы .xlsx, .xls, .csv")

    path = f"media/uploads/{file.file_name}"
    os.makedirs("media/uploads", exist_ok=True)
    await file.download(destination=path)

    data = await state.get_data()
    title = data["title"]
    points = data["points"]

    if ext == "csv":
        df = pd.read_csv(path)
    else:
        df = pd.read_excel(path)

    barcodes = df.iloc[:, 0].astype(str).str.strip().tolist()

    found = 0
    not_found = []

    with Session() as session:
        event = Event(title=title, points=points)
        session.add(event)
        session.commit()

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

    msg = f"""📊 Отчёт для мероприятия: {event.title}

👥 Найдено студентов: {found}
❌ Не найдено: {len(not_found)}"""

    if not_found:
        msg += "\n\n📍 Неизвестные штрихкоды:\n" + "\n".join(not_found[:10])
        if len(not_found) > 10:
            msg += f"\n...и ещё {len(not_found)-10} строк"

    await message.answer(msg)
    await state.clear()

@router.callback_query(F.data == "add_manual_barcode")
async def begin_manual_barcode(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ManualBarcodeState.AWAITING_EVENT_ID)
    await callback.message.answer("🔢 Введите ID мероприятия:")

@router.message(ManualBarcodeState.AWAITING_EVENT_ID)
async def get_event_id(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        return await message.answer("❗ Введите число")
    await state.update_data(event_id=int(message.text.strip()))
    await state.set_state(ManualBarcodeState.AWAITING_BARCODE)
    await message.answer("📥 Введите штрихкод для добавления:")

@router.message(ManualBarcodeState.AWAITING_BARCODE)
async def add_manual_barcode(message: Message, state: FSMContext):
    data = await state.get_data()
    event_id = data["event_id"]
    barcode = message.text.strip()

    with Session() as session:
        student = session.query(Student).filter_by(barcode=barcode).first()
        event = session.query(Event).get(event_id)

        if not student:
            return await message.answer("❌ Студент не найден.")

        student.balance += event.points
        session.add(Attendance(student_id=student.id, event_id=event_id))
        session.query(UnmatchedBarcode).filter_by(barcode=barcode, event_id=event_id).delete()
        session.commit()

    await message.answer("✅ Баркод добавлен и баллы начислены.")
    await state.clear()
