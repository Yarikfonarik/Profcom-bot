# handlers/events.py
from datetime import datetime
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy import text

from database import Session
from models import (
    Event, EventParticipant, Lecture, LectureScan,
    Student, EventTask, EventMerch, Task, Merchandise
)
from states import EventCreateState, LectureCreateState, EventScanState
from config import ADMIN_IDS

router = Router()


# ─────────────────────────────────────────────────────────────────────────────
#  МЕНЮ МЕРОПРИЯТИЙ (для всех)
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu_events")
async def events_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    is_admin = user_id in ADMIN_IDS

    with Session() as session:
        active_events = session.query(Event).filter_by(status='active').all()

        # Для каждого студента — какие мероприятия он посещает
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        my_event_ids = set()
        if student:
            parts = session.query(EventParticipant).filter_by(student_id=student.id).all()
            my_event_ids = {p.event_id for p in parts}

    buttons = []
    for ev in active_events:
        mark = "✅ " if ev.id in my_event_ids else ""
        buttons.append([InlineKeyboardButton(
            text=f"{mark}🎪 {ev.title}",
            callback_data=f"event_{ev.id}"
        )])

    if is_admin:
        buttons.append([InlineKeyboardButton(text="➕ Создать мероприятие", callback_data="create_event")])
        buttons.append([InlineKeyboardButton(text="📋 Все мероприятия",    callback_data="all_events_admin")])

    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_back")])

    try:
        await callback.message.delete()
    except Exception:
        pass

    text = "📥 Мероприятия:" if active_events else "📥 Активных мероприятий пока нет."
    await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


# ─────────────────────────────────────────────────────────────────────────────
#  СТРАНИЦА МЕРОПРИЯТИЯ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("event_") & ~F.data.startswith("event_task") & ~F.data.startswith("event_merch"))
async def event_page(callback: CallbackQuery):
    event_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    is_admin = user_id in ADMIN_IDS

    with Session() as session:
        event = session.query(Event).get(event_id)
        if not event:
            return await callback.answer("Мероприятие не найдено", show_alert=True)

        student = session.query(Student).filter_by(telegram_id=user_id).first()
        participant = None
        if student:
            participant = session.query(EventParticipant).filter_by(
                event_id=event_id, student_id=student.id
            ).first()

        lectures = session.query(Lecture).filter_by(event_id=event_id).all()
        participants_count = session.query(EventParticipant).filter_by(event_id=event_id).count()
        task_count = session.query(EventTask).filter_by(event_id=event_id).count()
        merch_count = session.query(EventMerch).filter_by(event_id=event_id).count()

    is_participant = participant is not None
    event_balance = participant.event_balance if participant else 0

    status_icon = "🟢" if event.status == 'active' else "🔴"
    msg = (
        f"{status_icon} *{event.title}*\n\n"
        f"💰 Баллы за лекцию: {event.points}\n"
        f"👥 Участников: {participants_count}\n"
        f"📚 Лекций: {len(lectures)}\n"
        f"📝 Заданий: {task_count}\n"
        f"🛍 Товаров: {merch_count}\n"
    )

    if is_participant:
        msg += f"\n🎯 Твои баллы мероприятия: *{event_balance}*"

    buttons = []

    if is_participant:
        buttons.append([InlineKeyboardButton(text="📝 Задания мероприятия", callback_data=f"event_tasks_{event_id}")])
        buttons.append([InlineKeyboardButton(text="🛍 Магазин мероприятия", callback_data=f"event_shop_{event_id}")])

    if is_admin:
        buttons.append([InlineKeyboardButton(text="👥 Сканировать участников", callback_data=f"scan_reg_{event_id}")])
        buttons.append([InlineKeyboardButton(text="📚 Управление лекциями",   callback_data=f"lectures_{event_id}")])
        buttons.append([InlineKeyboardButton(text="📝 Привязать задания",     callback_data=f"link_tasks_{event_id}")])
        buttons.append([InlineKeyboardButton(text="🛍 Привязать товары",      callback_data=f"link_merch_{event_id}")])
        if event.status == 'active':
            buttons.append([InlineKeyboardButton(text="🔴 Закрыть мероприятие", callback_data=f"close_event_{event_id}")])

    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_events")])

    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


# ─────────────────────────────────────────────────────────────────────────────
#  СОЗДАНИЕ МЕРОПРИЯТИЯ (admin)
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "create_event")
async def create_event_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав", show_alert=True)
    await callback.message.answer("🎪 Введите название мероприятия:")
    await state.set_state(EventCreateState.AWAITING_TITLE)


@router.message(EventCreateState.AWAITING_TITLE)
async def event_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await message.answer("💰 Баллы за посещение одной лекции (число):")
    await state.set_state(EventCreateState.AWAITING_POINTS)


@router.message(EventCreateState.AWAITING_POINTS)
async def event_points(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        return await message.answer("❗ Введите число")
    data = await state.get_data()
    points = int(message.text.strip())

    with Session() as session:
        ev = Event(title=data["title"], points=points, status='active')
        session.add(ev)
        session.commit()
        event_id = ev.id
        event_title = ev.title

    await state.clear()
    await message.answer(
        f"✅ Мероприятие *{event_title}* создано!\n\n"
        f"Теперь:\n"
        f"• Добавь лекции\n"
        f"• Привяжи задания и товары\n"
        f"• Начни сканировать участников",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Открыть мероприятие", callback_data=f"event_{event_id}")]
        ])
    )


# ─────────────────────────────────────────────────────────────────────────────
#  УПРАВЛЕНИЕ ЛЕКЦИЯМИ (admin)
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("lectures_"))
async def lectures_list(callback: CallbackQuery):
    event_id = int(callback.data.split("_")[1])
    with Session() as session:
        event = session.query(Event).get(event_id)
        lectures = session.query(Lecture).filter_by(event_id=event_id).all()

    buttons = []
    for lec in lectures:
        buttons.append([InlineKeyboardButton(
            text=f"📚 {lec.title} ({lec.points} б.)",
            callback_data=f"lecture_{lec.id}"
        )])
    buttons.append([InlineKeyboardButton(text="➕ Добавить лекцию", callback_data=f"add_lecture_{event_id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"event_{event_id}")])

    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        f"📚 Лекции — *{event.title}*:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data.startswith("add_lecture_"))
async def add_lecture_start(callback: CallbackQuery, state: FSMContext):
    event_id = int(callback.data.split("_")[2])
    await state.update_data(event_id=event_id)
    await callback.message.answer("📚 Введите название лекции:")
    await state.set_state(LectureCreateState.AWAITING_TITLE)


@router.message(LectureCreateState.AWAITING_TITLE)
async def lecture_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await message.answer("💰 Баллы за посещение этой лекции:")
    await state.set_state(LectureCreateState.AWAITING_POINTS)


@router.message(LectureCreateState.AWAITING_POINTS)
async def lecture_points(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        return await message.answer("❗ Введите число")
    data = await state.get_data()
    with Session() as session:
        lec = Lecture(event_id=data["event_id"], title=data["title"], points=int(message.text.strip()))
        session.add(lec)
        session.commit()
        event_id = data["event_id"]
    await state.clear()
    await message.answer(
        "✅ Лекция добавлена!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📚 К списку лекций", callback_data=f"lectures_{event_id}")]
        ])
    )


@router.callback_query(F.data.startswith("lecture_"))
async def lecture_page(callback: CallbackQuery):
    lecture_id = int(callback.data.split("_")[1])
    with Session() as session:
        lec = session.query(Lecture).get(lecture_id)
        if not lec:
            return await callback.answer("Лекция не найдена")
        scans_count = len(lec.scans)
        event_id = lec.event_id

    buttons = [
        [InlineKeyboardButton(text="📷 Начать сканирование", callback_data=f"start_scan_{lecture_id}")],
        [InlineKeyboardButton(text="📋 Список присутствующих", callback_data=f"scan_list_{lecture_id}")],
        [InlineKeyboardButton(text="🗑 Удалить лекцию", callback_data=f"del_lecture_{lecture_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"lectures_{event_id}")],
    ]

    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        f"📚 *{lec.title}*\n\n💰 Баллов: {lec.points}\n👥 Отсканировано: {scans_count}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data.startswith("del_lecture_"))
async def del_lecture(callback: CallbackQuery):
    lecture_id = int(callback.data.split("_")[2])
    with Session() as session:
        lec = session.query(Lecture).get(lecture_id)
        event_id = lec.event_id if lec else None
        if lec:
            session.execute(text("DELETE FROM lecture_scans WHERE lecture_id = :id"), {"id": lecture_id})
            session.delete(lec)
            session.commit()
    await callback.answer("🗑 Лекция удалена")
    callback.data = f"lectures_{event_id}"
    await lectures_list(callback)


# ─────────────────────────────────────────────────────────────────────────────
#  РЕЖИМ СКАНИРОВАНИЯ ЛЕКЦИЙ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("start_scan_"))
async def start_lecture_scan(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав", show_alert=True)
    lecture_id = int(callback.data.split("_")[2])

    with Session() as session:
        lec = session.query(Lecture).get(lecture_id)
        if not lec:
            return await callback.answer("Лекция не найдена")
        lec_title = lec.title
        lec_points = lec.points
        event_id = lec.event_id

    await state.update_data(lecture_id=lecture_id, event_id=event_id, scan_count=0)
    await state.set_state(EventScanState.SCAN_LECTURE)

    await callback.message.answer(
        f"📷 *Режим сканирования активен*\n\n"
        f"Лекция: *{lec_title}*\n"
        f"Баллов за посещение: *{lec_points}*\n\n"
        f"Введите или отсканируйте баркод студента.\n"
        f"Для остановки напишите /stop",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏹ Остановить сканирование", callback_data="stop_scan")]
        ])
    )


@router.callback_query(F.data == "stop_scan")
async def stop_scan_btn(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    count = data.get("scan_count", 0)
    lecture_id = data.get("lecture_id")
    await state.clear()
    await callback.message.answer(
        f"✅ Сканирование завершено.\nОтсканировано студентов: *{count}*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Список", callback_data=f"scan_list_{lecture_id}")]
        ])
    )


@router.message(EventScanState.SCAN_LECTURE)
async def process_lecture_scan(message: Message, state: FSMContext, bot: Bot):
    text_in = message.text.strip() if message.text else ""

    # Команда остановки
    if text_in.lower() in ("/stop", "stop", "стоп"):
        data = await state.get_data()
        count = data.get("scan_count", 0)
        lecture_id = data.get("lecture_id")
        await state.clear()
        return await message.answer(
            f"✅ Сканирование завершено. Отсканировано: *{count}*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📋 Список", callback_data=f"scan_list_{lecture_id}")]
            ])
        )

    barcode = text_in
    if not barcode:
        return

    data = await state.get_data()
    lecture_id = data["lecture_id"]
    event_id = data["event_id"]

    with Session() as session:
        lec = session.query(Lecture).get(lecture_id)
        student = session.query(Student).filter_by(barcode=barcode).first()

        if not student:
            return await message.answer(f"❌ Студент с баркодом `{barcode}` не найден.", parse_mode="Markdown")

        # Проверяем — участник ли
        participant = session.query(EventParticipant).filter_by(
            event_id=event_id, student_id=student.id
        ).first()
        if not participant:
            return await message.answer(
                f"⚠️ *{student.full_name}* не зарегистрирован на это мероприятие.",
                parse_mode="Markdown"
            )

        # Проверяем дубль
        existing = session.query(LectureScan).filter_by(
            lecture_id=lecture_id, student_id=student.id
        ).first()
        if existing:
            time_str = existing.scanned_at.strftime("%H:%M")
            return await message.answer(
                f"🔁 *{student.full_name}* — уже отсканирован сегодня в {time_str}",
                parse_mode="Markdown"
            )

        # Записываем скан
        scan = LectureScan(lecture_id=lecture_id, student_id=student.id)
        session.add(scan)

        # Начисляем баллы мероприятия
        participant.event_balance += lec.points
        session.commit()

        name = student.full_name
        new_balance = participant.event_balance
        points = lec.points

    # Обновляем счётчик
    scan_count = data.get("scan_count", 0) + 1
    await state.update_data(scan_count=scan_count)

    await message.answer(
        f"✅ *{name}*\n+{points} баллов мероприятия → итого: {new_balance}\n"
        f"_Всего на лекции: {scan_count}_",
        parse_mode="Markdown"
    )


# ─────────────────────────────────────────────────────────────────────────────
#  РЕГИСТРАЦИЯ УЧАСТНИКОВ (сканирование при входе)
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("scan_reg_"))
async def start_participant_scan(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав", show_alert=True)
    event_id = int(callback.data.split("_")[2])

    with Session() as session:
        event = session.query(Event).get(event_id)
        count = session.query(EventParticipant).filter_by(event_id=event_id).count()

    await state.update_data(event_id=event_id, reg_count=count)
    await state.set_state(EventScanState.REGISTER_PARTICIPANTS)

    await callback.message.answer(
        f"👥 *Регистрация участников*\n\n"
        f"Мероприятие: *{event.title}*\n"
        f"Уже зарегистрировано: {count}\n\n"
        f"Сканируйте баркоды для регистрации.\n"
        f"Для остановки напишите /stop",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏹ Остановить", callback_data="stop_reg_scan")]
        ])
    )


@router.callback_query(F.data == "stop_reg_scan")
async def stop_reg_scan(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    event_id = data.get("event_id")
    count = data.get("reg_count", 0)
    await state.clear()
    await callback.message.answer(
        f"✅ Регистрация завершена. Участников: *{count}*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="К мероприятию", callback_data=f"event_{event_id}")]
        ])
    )


@router.message(EventScanState.REGISTER_PARTICIPANTS)
async def process_participant_registration(message: Message, state: FSMContext):
    text_in = message.text.strip() if message.text else ""

    if text_in.lower() in ("/stop", "stop", "стоп"):
        data = await state.get_data()
        event_id = data.get("event_id")
        count = data.get("reg_count", 0)
        await state.clear()
        return await message.answer(
            f"✅ Регистрация завершена. Участников: *{count}*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="К мероприятию", callback_data=f"event_{event_id}")]
            ])
        )

    barcode = text_in
    data = await state.get_data()
    event_id = data["event_id"]

    with Session() as session:
        event = session.query(Event).get(event_id)
        student = session.query(Student).filter_by(barcode=barcode).first()

        if not student:
            return await message.answer(f"❌ Баркод `{barcode}` не найден.", parse_mode="Markdown")

        existing = session.query(EventParticipant).filter_by(
            event_id=event_id, student_id=student.id
        ).first()
        if existing:
            return await message.answer(f"🔁 *{student.full_name}* уже зарегистрирован.", parse_mode="Markdown")

        session.add(EventParticipant(event_id=event_id, student_id=student.id, event_balance=0))
        session.commit()
        name = student.full_name

    count = data.get("reg_count", 0) + 1
    await state.update_data(reg_count=count)
    await message.answer(f"✅ *{name}* зарегистрирован!\n_Всего участников: {count}_", parse_mode="Markdown")


# ─────────────────────────────────────────────────────────────────────────────
#  СПИСОК ОТСКАНИРОВАННЫХ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("scan_list_"))
async def scan_list(callback: CallbackQuery):
    lecture_id = int(callback.data.split("_")[2])
    with Session() as session:
        lec = session.query(Lecture).get(lecture_id)
        scans = session.query(LectureScan).filter_by(lecture_id=lecture_id).order_by(LectureScan.scanned_at).all()
        rows = []
        for s in scans:
            student = session.query(Student).get(s.student_id)
            time_str = s.scanned_at.strftime("%H:%M")
            rows.append(f"{len(rows)+1}. {student.full_name} — {time_str}")

    msg = f"📋 *{lec.title}* — присутствующие ({len(rows)}):\n\n"
    if rows:
        msg += "\n".join(rows)
    else:
        msg += "Никто ещё не отсканирован."

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📷 Продолжить сканирование", callback_data=f"start_scan_{lecture_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"lecture_{lecture_id}")],
    ])
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=kb)


# ─────────────────────────────────────────────────────────────────────────────
#  ПРИВЯЗКА ЗАДАНИЙ И ТОВАРОВ К МЕРОПРИЯТИЮ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("link_tasks_"))
async def link_tasks_page(callback: CallbackQuery):
    event_id = int(callback.data.split("_")[2])
    with Session() as session:
        event = session.query(Event).get(event_id)
        all_tasks = session.query(Task).filter_by(is_deleted=False).all()
        linked_ids = {et.task_id for et in session.query(EventTask).filter_by(event_id=event_id).all()}

    buttons = []
    for t in all_tasks:
        mark = "✅ " if t.id in linked_ids else "➕ "
        cb = f"unlink_task_{event_id}_{t.id}" if t.id in linked_ids else f"do_link_task_{event_id}_{t.id}"
        buttons.append([InlineKeyboardButton(text=f"{mark}{t.title} ({t.points} б.)", callback_data=cb)])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"event_{event_id}")])

    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        f"📝 Задания мероприятия *{event.title}*:\n✅ — уже привязано, ➕ — добавить",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data.startswith("do_link_task_"))
async def do_link_task(callback: CallbackQuery):
    _, _, event_id, task_id = callback.data.split("_", 3)
    event_id, task_id = int(event_id), int(task_id)
    with Session() as session:
        exists = session.query(EventTask).filter_by(event_id=event_id, task_id=task_id).first()
        if not exists:
            session.add(EventTask(event_id=event_id, task_id=task_id))
            session.commit()
    await callback.answer("✅ Задание привязано")
    callback.data = f"link_tasks_{event_id}"
    await link_tasks_page(callback)


@router.callback_query(F.data.startswith("unlink_task_"))
async def unlink_task(callback: CallbackQuery):
    _, _, event_id, task_id = callback.data.split("_", 3)
    event_id, task_id = int(event_id), int(task_id)
    with Session() as session:
        et = session.query(EventTask).filter_by(event_id=event_id, task_id=task_id).first()
        if et:
            session.delete(et)
            session.commit()
    await callback.answer("🗑 Задание откреплено")
    callback.data = f"link_tasks_{event_id}"
    await link_tasks_page(callback)


@router.callback_query(F.data.startswith("link_merch_"))
async def link_merch_page(callback: CallbackQuery):
    event_id = int(callback.data.split("_")[2])
    with Session() as session:
        event = session.query(Event).get(event_id)
        all_merch = session.query(Merchandise).filter_by(is_deleted=False).all()
        linked_ids = {em.merch_id for em in session.query(EventMerch).filter_by(event_id=event_id).all()}

    buttons = []
    for m in all_merch:
        mark = "✅ " if m.id in linked_ids else "➕ "
        cb = f"unlink_merch_{event_id}_{m.id}" if m.id in linked_ids else f"do_link_merch_{event_id}_{m.id}"
        buttons.append([InlineKeyboardButton(text=f"{mark}{m.name} ({m.price} б.)", callback_data=cb)])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"event_{event_id}")])

    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        f"🛍 Товары мероприятия *{event.title}*:\n✅ — уже привязано, ➕ — добавить",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data.startswith("do_link_merch_"))
async def do_link_merch(callback: CallbackQuery):
    _, _, event_id, merch_id = callback.data.split("_", 3)
    event_id, merch_id = int(event_id), int(merch_id)
    with Session() as session:
        exists = session.query(EventMerch).filter_by(event_id=event_id, merch_id=merch_id).first()
        if not exists:
            session.add(EventMerch(event_id=event_id, merch_id=merch_id))
            session.commit()
    await callback.answer("✅ Товар привязан")
    callback.data = f"link_merch_{event_id}"
    await link_merch_page(callback)


@router.callback_query(F.data.startswith("unlink_merch_"))
async def unlink_merch(callback: CallbackQuery):
    _, _, event_id, merch_id = callback.data.split("_", 3)
    event_id, merch_id = int(event_id), int(merch_id)
    with Session() as session:
        em = session.query(EventMerch).filter_by(event_id=event_id, merch_id=merch_id).first()
        if em:
            session.delete(em)
            session.commit()
    await callback.answer("🗑 Товар откреплён")
    callback.data = f"link_merch_{event_id}"
    await link_merch_page(callback)


# ─────────────────────────────────────────────────────────────────────────────
#  ЗАДАНИЯ МЕРОПРИЯТИЯ (для студента-участника)
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("event_tasks_"))
async def event_tasks_page(callback: CallbackQuery):
    event_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id

    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        participant = session.query(EventParticipant).filter_by(
            event_id=event_id, student_id=student.id if student else -1
        ).first() if student else None

        if not participant:
            return await callback.answer("❌ Ты не участник этого мероприятия", show_alert=True)

        event = session.query(Event).get(event_id)
        linked = session.query(EventTask).filter_by(event_id=event_id).all()
        task_ids = [et.task_id for et in linked]
        tasks = session.query(Task).filter(Task.id.in_(task_ids), Task.is_deleted == False).all() if task_ids else []

        # Статусы выполнения
        from models import TaskVerification
        verifs = {}
        for t in tasks:
            v = session.query(TaskVerification).filter_by(student_id=student.id, task_id=t.id).first()
            if v:
                verifs[t.id] = v

    buttons = []
    for t in tasks:
        v = verifs.get(t.id)
        if v and v.status == "approved":
            emoji = "✅"
        elif v and v.status == "pending":
            emoji = "⏳"
        else:
            emoji = "❌"
        buttons.append([InlineKeyboardButton(
            text=f"{emoji} {t.title} — {t.points} б.",
            callback_data=f"etask_{event_id}_{t.id}"
        )])

    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"event_{event_id}")])

    try:
        await callback.message.delete()
    except Exception:
        pass
    msg = f"📝 Задания мероприятия *{event.title}*\n💰 Баллы мероприятия: {participant.event_balance}"
    await callback.message.answer(
        msg, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data.startswith("etask_"))
async def event_task_view(callback: CallbackQuery, state: FSMContext):
    _, event_id, task_id = callback.data.split("_", 2)
    event_id, task_id = int(event_id), int(task_id)
    user_id = callback.from_user.id

    with Session() as session:
        task = session.query(Task).get(task_id)
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        from models import TaskVerification
        verification = session.query(TaskVerification).filter_by(
            student_id=student.id if student else -1, task_id=task_id
        ).first() if student else None

    msg = (
        f"📌 *{task.title}*\n\n"
        f"{task.description or ''}\n\n"
        f"💯 Баллов: {task.points} (мероприятия)\n"
        f"🔍 Проверка: {'по ответу' if task.verification_type == 'auto' else 'по доказательству'}"
    )

    buttons = []
    if verification and verification.status == "approved":
        msg += "\n\n✅ Уже выполнено"
    elif verification and verification.status == "pending":
        msg += "\n\n⏳ На проверке"
    else:
        buttons.append([InlineKeyboardButton(text="✍️ Выполнить", callback_data=f"do_etask_{event_id}_{task_id}")])

    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"event_tasks_{event_id}")])

    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("do_etask_"))
async def start_event_task(callback: CallbackQuery, state: FSMContext):
    _, event_id, task_id = callback.data.split("_", 2)
    event_id, task_id = int(event_id), int(task_id)
    with Session() as session:
        task = session.query(Task).get(task_id)
    await state.update_data(task_id=task_id, event_id=event_id, is_event_task=True)
    if task.verification_type == "auto":
        await callback.message.answer("✏️ Введите ваш ответ:")
        from states import TaskState
        await state.set_state(TaskState.waiting_answer)
    else:
        await callback.message.answer(f"📤 {task.proof_text or 'Отправьте доказательство (текст или фото)'}")
        from states import TaskState
        await state.set_state(TaskState.waiting_proof)


# ─────────────────────────────────────────────────────────────────────────────
#  МАГАЗИН МЕРОПРИЯТИЯ (для студента-участника)
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("event_shop_"))
async def event_shop_page(callback: CallbackQuery):
    event_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id

    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        participant = session.query(EventParticipant).filter_by(
            event_id=event_id, student_id=student.id if student else -1
        ).first() if student else None

        if not participant:
            return await callback.answer("❌ Ты не участник этого мероприятия", show_alert=True)

        event = session.query(Event).get(event_id)
        linked = session.query(EventMerch).filter_by(event_id=event_id).all()
        merch_ids = [em.merch_id for em in linked]
        items = session.query(Merchandise).filter(
            Merchandise.id.in_(merch_ids),
            Merchandise.is_deleted == False
        ).all() if merch_ids else []

        # Какие уже куплены
        from models import Purchase
        bought = {p.merch_id for p in session.query(Purchase).filter_by(student_id=student.id).all()} if student else set()
        balance = participant.event_balance

    buttons = []
    for item in items:
        if item.id in bought:
            emoji = "✅"
        elif item.stock <= 0:
            emoji = "🚫"
        else:
            emoji = "🛒"
        buttons.append([InlineKeyboardButton(
            text=f"{emoji} {item.name} — {item.price} б.",
            callback_data=f"eshop_{event_id}_{item.id}"
        )])

    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"event_{event_id}")])

    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        f"🛍 Магазин мероприятия *{event.title}*\n💰 Твои баллы: {balance}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data.startswith("eshop_"))
async def event_shop_item(callback: CallbackQuery):
    _, event_id, item_id = callback.data.split("_", 2)
    event_id, item_id = int(event_id), int(item_id)
    user_id = callback.from_user.id

    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        participant = session.query(EventParticipant).filter_by(
            event_id=event_id, student_id=student.id if student else -1
        ).first() if student else None
        item = session.query(Merchandise).get(item_id)
        from models import Purchase
        already_bought = session.query(Purchase).filter_by(
            student_id=student.id if student else -1, merch_id=item_id
        ).first() is not None if student else False

    if not item or not participant:
        return await callback.answer("Ошибка", show_alert=True)

    balance = participant.event_balance
    can_buy = balance >= item.price and item.stock > 0 and not already_bought

    caption = (
        f"🛍 *{item.name}*\n\n"
        f"{item.description or ''}\n\n"
        f"💰 Цена: {item.price} б. мероприятия\n"
        f"📦 Остаток: {item.stock}\n"
        f"💳 Твой баланс: {balance}"
    )

    buttons = []
    if already_bought:
        buttons.append([InlineKeyboardButton(text="✅ Уже куплено", callback_data="noop_shop")])
    elif item.stock <= 0:
        buttons.append([InlineKeyboardButton(text="🚫 Нет в наличии", callback_data="noop_shop")])
    elif can_buy:
        buttons.append([InlineKeyboardButton(text="🛒 Купить", callback_data=f"ebuy_{event_id}_{item_id}")])
    else:
        buttons.append([InlineKeyboardButton(text="❌ Недостаточно баллов", callback_data="noop_shop")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"event_shop_{event_id}")])

    try:
        await callback.message.delete()
    except Exception:
        pass

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    if item.photo_file_id:
        await callback.message.answer_photo(photo=item.photo_file_id, caption=caption, parse_mode="Markdown", reply_markup=kb)
    else:
        await callback.message.answer(caption, parse_mode="Markdown", reply_markup=kb)


@router.callback_query(F.data.startswith("ebuy_"))
async def event_buy(callback: CallbackQuery):
    _, event_id, item_id = callback.data.split("_", 2)
    event_id, item_id = int(event_id), int(item_id)
    user_id = callback.from_user.id

    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        participant = session.query(EventParticipant).filter_by(
            event_id=event_id, student_id=student.id if student else -1
        ).first()
        item = session.query(Merchandise).get(item_id)
        from models import Purchase

        if not student or not participant or not item:
            return await callback.answer("Ошибка", show_alert=True)
        if participant.event_balance < item.price:
            return await callback.answer(f"❌ Нужно {item.price} б., у тебя {participant.event_balance}", show_alert=True)
        if item.stock <= 0:
            return await callback.answer("❌ Товар закончился", show_alert=True)
        if session.query(Purchase).filter_by(student_id=student.id, merch_id=item_id).first():
            return await callback.answer("❌ Уже куплено", show_alert=True)

        participant.event_balance -= item.price
        item.stock -= 1
        session.add(Purchase(student_id=student.id, merch_id=item_id, quantity=1, total_points=item.price))
        session.commit()
        item_name = item.name

    await callback.answer(f"✅ Куплено: {item_name}!", show_alert=True)


# ─────────────────────────────────────────────────────────────────────────────
#  ЗАКРЫТИЕ МЕРОПРИЯТИЯ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("close_event_"))
async def confirm_close_event(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав", show_alert=True)
    event_id = int(callback.data.split("_")[2])
    with Session() as session:
        event = session.query(Event).get(event_id)
        count = session.query(EventParticipant).filter_by(event_id=event_id).count()

    await callback.message.answer(
        f"⚠️ *Закрыть мероприятие «{event.title}»?*\n\n"
        f"Баллы мероприятия сгорят у {count} участников.\n"
        f"Основные баллы не затрагиваются.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Закрыть", callback_data=f"do_close_{event_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"event_{event_id}"),
        ]])
    )


@router.callback_query(F.data.startswith("do_close_"))
async def do_close_event(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав", show_alert=True)
    event_id = int(callback.data.split("_")[2])

    with Session() as session:
        event = session.query(Event).get(event_id)
        event.status = 'closed'
        # Обнуляем event_balance только у участников этого мероприятия
        session.execute(
            text("UPDATE event_participants SET event_balance = 0 WHERE event_id = :eid"),
            {"eid": event_id}
        )
        session.commit()
        title = event.title

    await callback.answer(f"✅ Мероприятие «{title}» закрыто!", show_alert=True)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        f"🔴 Мероприятие *{title}* закрыто.\nБаллы участников обнулены.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📥 К мероприятиям", callback_data="menu_events")]
        ])
    )


# ─────────────────────────────────────────────────────────────────────────────
#  ВСЕ МЕРОПРИЯТИЯ (admin)
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "all_events_admin")
async def all_events_admin(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав", show_alert=True)
    with Session() as session:
        events = session.query(Event).order_by(Event.created_at.desc()).all()

    buttons = []
    for ev in events:
        icon = "🟢" if ev.status == 'active' else "🔴"
        buttons.append([InlineKeyboardButton(
            text=f"{icon} {ev.title}",
            callback_data=f"event_{ev.id}"
        )])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_events")])

    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        "📋 Все мероприятия:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
