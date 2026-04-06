# handlers/events.py — уведомления + новая страница участника + стартовые баллы
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
#  МЕНЮ МЕРОПРИЯТИЙ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu_events")
async def events_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    is_admin = user_id in ADMIN_IDS

    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        my_event_ids = set()
        if student:
            parts = session.query(EventParticipant).filter_by(student_id=student.id).all()
            my_event_ids = {p.event_id for p in parts}

        all_active = session.query(Event).filter_by(status='active').all()
        visible = []
        for ev in all_active:
            if is_admin or ev.id in my_event_ids or not ev.hidden:
                visible.append(ev)

    buttons = []
    for ev in visible:
        mark = "✅ " if ev.id in my_event_ids else ""
        lock = "🔒 " if ev.hidden and is_admin else ""
        buttons.append([InlineKeyboardButton(
            text=f"{mark}{lock}🎪 {ev.title}",
            callback_data=f"event_{ev.id}"
        )])

    if is_admin:
        buttons.append([InlineKeyboardButton(text="➕ Создать мероприятие", callback_data="create_event")])
        buttons.append([InlineKeyboardButton(text="📋 Все мероприятия",     callback_data="all_events_admin")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_back")])

    try: await callback.message.delete()
    except Exception: pass
    text = "📥 Мероприятия:" if visible else "📥 Активных мероприятий пока нет."
    await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


# ─────────────────────────────────────────────────────────────────────────────
#  СТРАНИЦА МЕРОПРИЯТИЯ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("event_") & ~F.data.startswith("event_task") & ~F.data.startswith("event_merch") & ~F.data.startswith("event_shop"))
async def event_page(callback: CallbackQuery):
    raw = callback.data[6:]
    if not raw.isdigit(): return
    event_id = int(raw)
    user_id = callback.from_user.id
    is_admin = user_id in ADMIN_IDS

    with Session() as session:
        event = session.query(Event).get(event_id)
        if not event: return await callback.answer("Мероприятие не найдено", show_alert=True)

        student = session.query(Student).filter_by(telegram_id=user_id).first()
        participant = None
        if student:
            participant = session.query(EventParticipant).filter_by(event_id=event_id, student_id=student.id).first()

        lectures = session.query(Lecture).filter_by(event_id=event_id).all()
        participants_count = session.query(EventParticipant).filter_by(event_id=event_id).count()
        task_count = session.query(EventTask).filter_by(event_id=event_id).count()
        merch_count = session.query(EventMerch).filter_by(event_id=event_id).count()

        # Для участника — статистика
        tasks_done = 0
        purchases_count = 0
        lectures_attended = 0
        if participant and student:
            tasks_done = session.execute(text("""
                SELECT COUNT(*) FROM task_verifications tv
                JOIN event_tasks et ON et.task_id = tv.task_id
                WHERE tv.student_id = :sid AND et.event_id = :eid AND tv.status = 'approved'
            """), {"sid": student.id, "eid": event_id}).scalar()
            purchases_count = session.execute(text("""
                SELECT COUNT(*) FROM purchases p
                JOIN event_merch em ON em.merch_id = p.merch_id
                WHERE p.student_id = :sid AND em.event_id = :eid
            """), {"sid": student.id, "eid": event_id}).scalar()
            lectures_attended = session.execute(text("""
                SELECT COUNT(*) FROM lecture_scans ls
                JOIN lectures l ON l.id = ls.lecture_id
                WHERE ls.student_id = :sid AND l.event_id = :eid
            """), {"sid": student.id, "eid": event_id}).scalar()

    is_participant = participant is not None
    event_balance = participant.event_balance if participant else 0

    try: await callback.message.delete()
    except Exception: pass

    # ── Вид для участника ──────────────────────────────────────────────────
    if is_participant and not is_admin:
        msg = (
            f"🎪 *{event.title}*\n\n"
            f"💰 Баллов мероприятия: *{event_balance}*\n"
            f"📚 Лекций посещено: {lectures_attended} / {len(lectures)}\n"
            f"📝 Заданий выполнено: {tasks_done}\n"
            f"🛍 Покупок: {purchases_count}\n"
        )
        buttons = []
        if event.has_tasks:
            buttons.append([InlineKeyboardButton(text="📝 Задания мероприятия", callback_data=f"event_tasks_{event_id}")])
        if event.has_shop:
            buttons.append([InlineKeyboardButton(text="🛍 Магазин мероприятия", callback_data=f"event_shop_{event_id}")])
        buttons.append([InlineKeyboardButton(text="ℹ️ Информация",             callback_data=f"event_info_{event_id}")])
        buttons.append([InlineKeyboardButton(text="🆘 Помощь",                 callback_data="support")])
        buttons.append([InlineKeyboardButton(text="⬅️ Назад",                 callback_data="menu_events")])

        if event.image_file_id:
            await callback.message.answer_photo(
                photo=event.image_file_id, caption=msg, parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
            )
        else:
            await callback.message.answer(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        return

    # ── Вид для НЕ-участника (публичная страница) ─────────────────────────
    if not is_participant and not is_admin:
        msg = f"🎪 *{event.title}*\n\n"
        if event.description:
            msg += f"{event.description}\n\n"
        if event.event_date:
            msg += f"📅 Дата: {event.event_date}\n"
        if event.how_to_join:
            msg += f"\n🚀 *Как попасть:*\n{event.how_to_join}\n"

        buttons = [[InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_events")]]
        if event.image_file_id:
            await callback.message.answer_photo(
                photo=event.image_file_id, caption=msg, parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
            )
        else:
            await callback.message.answer(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        return

    # ── Вид для АДМИНА ────────────────────────────────────────────────────
    status_icon = "🟢" if event.status == 'active' else "🔴"
    vis_text = "🔒 Скрытое" if event.hidden else "👁 Открытое"
    msg = (
        f"{status_icon} *{event.title}*\n"
        f"Видимость: {vis_text}\n\n"
        f"💰 Стартовые баллы: {event.points}\n"
        f"👥 Участников: {participants_count}\n"
        f"📚 Лекций: {len(lectures)}\n"
        f"📝 Заданий: {task_count}\n"
        f"🛍 Товаров: {merch_count}\n"
        f"Функции: {'📚' if event.has_lectures else '—'} {'📝' if event.has_tasks else '—'} {'🛍' if event.has_shop else '—'}\n"
    )

    buttons = []
    # Участие самого админа
    if is_participant:
        if event.has_tasks:
            buttons.append([InlineKeyboardButton(text="📝 Задания", callback_data=f"event_tasks_{event_id}")])
        if event.has_shop:
            buttons.append([InlineKeyboardButton(text="🛍 Магазин", callback_data=f"event_shop_{event_id}")])

    # Управление
    buttons.append([InlineKeyboardButton(text="👥 Сканировать участников", callback_data=f"scan_reg_{event_id}")])
    if event.has_lectures:
        buttons.append([InlineKeyboardButton(text="📚 Лекции",           callback_data=f"lectures_{event_id}")])
    if event.has_tasks:
        buttons.append([InlineKeyboardButton(text="📝 Управление заданиями", callback_data=f"link_tasks_{event_id}")])
    if event.has_shop:
        buttons.append([InlineKeyboardButton(text="🛍 Управление товарами",  callback_data=f"link_merch_{event_id}")])

    if event.hidden:
        buttons.append([InlineKeyboardButton(text="👁 Сделать видимым",  callback_data=f"toggle_hidden_{event_id}")])
    else:
        buttons.append([InlineKeyboardButton(text="🔒 Сделать скрытым",  callback_data=f"toggle_hidden_{event_id}")])

    if event.status == 'active':
        buttons.append([InlineKeyboardButton(text="🔴 Закрыть мероприятие", callback_data=f"close_event_{event_id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_events")])

    if event.image_file_id:
        await callback.message.answer_photo(photo=event.image_file_id, caption=msg, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    else:
        await callback.message.answer(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


# ─────────────────────────────────────────────────────────────────────────────
#  ИНФОРМАЦИЯ О МЕРОПРИЯТИИ (кнопка для участников)
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("event_info_"))
async def event_info(callback: CallbackQuery):
    event_id = int(callback.data.split("_")[2])
    with Session() as session:
        event = session.query(Event).get(event_id)

    if not event: return await callback.answer("Не найдено")

    msg = f"ℹ️ *{event.title}*\n\n"
    if event.description:
        msg += f"{event.description}\n\n"
    if event.event_date:
        msg += f"📅 Дата: {event.event_date}\n"
    if event.how_to_join:
        msg += f"\n🚀 Как попасть:\n{event.how_to_join}\n"
    if not event.description and not event.event_date and not event.how_to_join:
        msg += "Дополнительная информация не добавлена."

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"event_{event_id}")]])
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=kb)


# ─────────────────────────────────────────────────────────────────────────────
#  ПЕРЕКЛЮЧЕНИЕ ВИДИМОСТИ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("toggle_hidden_"))
async def toggle_hidden(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔ Нет прав", show_alert=True)
    event_id = int(callback.data.split("_")[2])
    with Session() as session:
        event = session.query(Event).get(event_id)
        event.hidden = not event.hidden
        session.commit()
        status = "скрытым 🔒" if event.hidden else "видимым 👁"
    await callback.answer(f"✅ Мероприятие стало {status}")
    callback.data = f"event_{event_id}"
    await event_page(callback)


# ─────────────────────────────────────────────────────────────────────────────
#  СОЗДАНИЕ МЕРОПРИЯТИЯ (новый флоу)
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "create_event")
async def create_event_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔ Нет прав", show_alert=True)
    await callback.message.answer("🎪 Введите название мероприятия:")
    await state.set_state(EventCreateState.AWAITING_TITLE)


@router.message(EventCreateState.AWAITING_TITLE)
async def event_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await message.answer(
        "💰 Стартовые баллы за участие (начисляются при регистрации).\n\n"
        "Введите число или напишите «0» если не нужны:"
    )
    await state.set_state(EventCreateState.AWAITING_POINTS)


@router.message(EventCreateState.AWAITING_POINTS)
async def event_points(message: Message, state: FSMContext):
    if not message.text.strip().isdigit(): return await message.answer("❗ Введите число (или 0)")
    await state.update_data(points=int(message.text.strip()))
    await message.answer(
        "📅 Введите дату и время мероприятия (или напишите «нет»):\nПример: 15 апреля 2025, 14:00"
    )
    await state.set_state(EventCreateState.AWAITING_DATE)


@router.message(EventCreateState.AWAITING_DATE)
async def event_date(message: Message, state: FSMContext):
    val = message.text.strip()
    await state.update_data(event_date=None if val.lower() == "нет" else val)
    await message.answer("📝 Краткое описание мероприятия (или «нет»):")
    await state.set_state(EventCreateState.AWAITING_DESCRIPTION)


@router.message(EventCreateState.AWAITING_DESCRIPTION)
async def event_description(message: Message, state: FSMContext):
    val = message.text.strip()
    await state.update_data(description=None if val.lower() == "нет" else val)
    await message.answer("🖼 Отправьте картинку мероприятия (или напишите «нет»):")
    await state.set_state(EventCreateState.AWAITING_IMAGE)


@router.message(EventCreateState.AWAITING_IMAGE, F.photo)
async def event_image(message: Message, state: FSMContext):
    await state.update_data(image_file_id=message.photo[-1].file_id)
    await _ask_how_to_join(message, state)


@router.message(EventCreateState.AWAITING_IMAGE)
async def event_no_image(message: Message, state: FSMContext):
    await state.update_data(image_file_id=None)
    await _ask_how_to_join(message, state)


async def _ask_how_to_join(message, state):
    await message.answer("🚀 Как попасть на мероприятие? (или «нет»):")
    await state.set_state(EventCreateState.AWAITING_HOW_TO_JOIN)


@router.message(EventCreateState.AWAITING_HOW_TO_JOIN)
async def event_how_to_join(message: Message, state: FSMContext):
    val = message.text.strip()
    await state.update_data(how_to_join=None if val.lower() == "нет" else val)

    await message.answer(
        "Видимость мероприятия:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👁 Открытое (все видят)", callback_data="ev_vis_0")],
            [InlineKeyboardButton(text="🔒 Скрытое (только после скана)", callback_data="ev_vis_1")],
        ])
    )
    await state.set_state(EventCreateState.AWAITING_HIDDEN)


@router.callback_query(F.data.startswith("ev_vis_"))
async def event_hidden_choice(callback: CallbackQuery, state: FSMContext):
    hidden = callback.data == "ev_vis_1"
    await state.update_data(hidden=hidden)

    await callback.message.answer(
        "Какие функции включить?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📚 Лекции + 📝 Задания + 🛍 Магазин", callback_data="ev_feat_all")],
            [InlineKeyboardButton(text="📚 Только лекции",                     callback_data="ev_feat_lect")],
            [InlineKeyboardButton(text="📝 Только задания",                    callback_data="ev_feat_tasks")],
            [InlineKeyboardButton(text="🛍 Только магазин",                    callback_data="ev_feat_shop")],
            [InlineKeyboardButton(text="💰 Только баллы за участие",           callback_data="ev_feat_none")],
        ])
    )
    await state.set_state(EventCreateState.AWAITING_FEATURES)


@router.callback_query(F.data.startswith("ev_feat_"))
async def event_features(callback: CallbackQuery, state: FSMContext):
    feat = callback.data.split("_")[2]
    feat_map = {
        "all":   (True,  True,  True),
        "lect":  (True,  False, False),
        "tasks": (False, True,  False),
        "shop":  (False, False, True),
        "none":  (False, False, False),
    }
    has_lect, has_tasks, has_shop = feat_map.get(feat, (True, True, True))
    await state.update_data(has_lectures=has_lect, has_tasks=has_tasks, has_shop=has_shop)
    await _finish_event_create(callback.message, state)


async def _finish_event_create(message, state):
    data = await state.get_data()
    with Session() as session:
        ev = Event(
            title=data["title"], points=data["points"],
            event_date=data.get("event_date"),
            description=data.get("description"),
            image_file_id=data.get("image_file_id"),
            how_to_join=data.get("how_to_join"),
            hidden=data.get("hidden", False),
            has_lectures=data.get("has_lectures", True),
            has_tasks=data.get("has_tasks", True),
            has_shop=data.get("has_shop", True),
            status='active'
        )
        session.add(ev)
        session.commit()
        event_id = ev.id
        event_title = ev.title

    await state.clear()
    vis = "скрытое 🔒" if data.get("hidden") else "открытое 👁"
    await message.answer(
        f"✅ Мероприятие *{event_title}* создано!\nВидимость: {vis}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Открыть мероприятие", callback_data=f"event_{event_id}")]
        ])
    )


# ─────────────────────────────────────────────────────────────────────────────
#  ЛЕКЦИИ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("lectures_"))
async def lectures_list(callback: CallbackQuery):
    event_id = int(callback.data.split("_")[1])
    with Session() as session:
        event = session.query(Event).get(event_id)
        lectures = session.query(Lecture).filter_by(event_id=event_id).all()

    buttons = [[InlineKeyboardButton(text=f"📚 {l.title} ({l.points} б.)", callback_data=f"lecture_{l.id}")] for l in lectures]
    buttons.append([InlineKeyboardButton(text="➕ Добавить лекцию", callback_data=f"add_lecture_{event_id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"event_{event_id}")])
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(f"📚 Лекции — *{event.title}*:", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("add_lecture_"))
async def add_lecture_start(callback: CallbackQuery, state: FSMContext):
    event_id = int(callback.data.split("_")[2])
    await state.update_data(event_id=event_id)
    await callback.message.answer("📚 Название лекции:")
    await state.set_state(LectureCreateState.AWAITING_TITLE)


@router.message(LectureCreateState.AWAITING_TITLE)
async def lecture_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await message.answer("💰 Баллы за посещение:")
    await state.set_state(LectureCreateState.AWAITING_POINTS)


@router.message(LectureCreateState.AWAITING_POINTS)
async def lecture_points(message: Message, state: FSMContext):
    if not message.text.strip().isdigit(): return await message.answer("❗ Число")
    data = await state.get_data()
    with Session() as session:
        session.add(Lecture(event_id=data["event_id"], title=data["title"], points=int(message.text.strip())))
        session.commit()
    await state.clear()
    await message.answer("✅ Лекция добавлена!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 К лекциям", callback_data=f"lectures_{data['event_id']}")]
    ]))


@router.callback_query(F.data.startswith("lecture_") & ~F.data.startswith("lecture_scan"))
async def lecture_page(callback: CallbackQuery):
    lecture_id = int(callback.data.split("_")[1])
    with Session() as session:
        lec = session.query(Lecture).get(lecture_id)
        if not lec: return await callback.answer("Не найдена")
        scans_count = len(lec.scans)
        event_id = lec.event_id

    buttons = [
        [InlineKeyboardButton(text="📷 Начать сканирование",  callback_data=f"start_scan_{lecture_id}")],
        [InlineKeyboardButton(text="📋 Список присутствующих", callback_data=f"scan_list_{lecture_id}")],
        [InlineKeyboardButton(text="🗑 Удалить лекцию",       callback_data=f"del_lecture_{lecture_id}")],
        [InlineKeyboardButton(text="⬅️ Назад",               callback_data=f"lectures_{event_id}")],
    ]
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(
        f"📚 *{lec.title}*\n💰 {lec.points} б. | 👥 Отсканировано: {scans_count}",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data.startswith("del_lecture_"))
async def del_lecture(callback: CallbackQuery):
    lid = int(callback.data.split("_")[2])
    with Session() as session:
        lec = session.query(Lecture).get(lid)
        event_id = lec.event_id if lec else None
        if lec:
            session.execute(text("DELETE FROM lecture_scans WHERE lecture_id=:id"), {"id": lid})
            session.delete(lec)
            session.commit()
    await callback.answer("🗑 Удалена")
    callback.data = f"lectures_{event_id}"
    await lectures_list(callback)


# ─────────────────────────────────────────────────────────────────────────────
#  СКАНИРОВАНИЕ ЛЕКЦИЙ (с уведомлением студенту)
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("start_scan_"))
async def start_lecture_scan(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔ Нет прав", show_alert=True)
    lid = int(callback.data.split("_")[2])
    with Session() as session:
        lec = session.query(Lecture).get(lid)
        if not lec: return await callback.answer("Не найдена")
        lec_title, lec_points, event_id = lec.title, lec.points, lec.event_id
        scans_count = len(lec.scans)

    await state.update_data(lecture_id=lid, event_id=event_id, scan_count=scans_count)
    await state.set_state(EventScanState.SCAN_LECTURE)

    stop_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏹ Остановить", callback_data="stop_scan")]])
    await callback.message.answer(
        f"📷 *Сканирование лекции*\n*{lec_title}* | {lec_points} б.\nУже: {scans_count}\n\nВводите баркод. /stop для остановки.",
        parse_mode="Markdown", reply_markup=stop_kb
    )


@router.callback_query(F.data == "stop_scan")
async def stop_scan_btn(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lid = data.get("lecture_id")
    count = data.get("scan_count", 0)
    await state.clear()
    await callback.message.answer(
        f"✅ Сканирование завершено. Всего: *{count}*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Список", callback_data=f"scan_list_{lid}")],
            [InlineKeyboardButton(text="⬅️ К лекции", callback_data=f"lecture_{lid}")],
        ])
    )


@router.message(EventScanState.SCAN_LECTURE)
async def process_lecture_scan(message: Message, state: FSMContext, bot: Bot):
    text_in = (message.text or "").strip()
    stop_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏹ Остановить", callback_data="stop_scan")]])

    if text_in.lower() in ("/stop", "stop", "стоп"):
        data = await state.get_data()
        lid = data.get("lecture_id")
        count = data.get("scan_count", 0)
        await state.clear()
        return await message.answer(
            f"✅ Готово. Отсканировано: *{count}*", parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📋 Список", callback_data=f"scan_list_{lid}")]])
        )

    data = await state.get_data()
    lid = data["lecture_id"]
    event_id = data["event_id"]

    with Session() as session:
        lec = session.query(Lecture).get(lid)
        student = session.query(Student).filter_by(barcode=text_in).first()

        if not student:
            return await message.answer(f"❌ Баркод `{text_in}` не найден.", parse_mode="Markdown", reply_markup=stop_kb)

        participant = session.query(EventParticipant).filter_by(event_id=event_id, student_id=student.id).first()
        if not participant:
            return await message.answer(f"⚠️ *{student.full_name}* не участник.", parse_mode="Markdown", reply_markup=stop_kb)

        existing = session.query(LectureScan).filter_by(lecture_id=lid, student_id=student.id).first()
        if existing:
            time_str = existing.scanned_at.strftime("%H:%M")
            return await message.answer(f"🔁 *{student.full_name}* — уже в {time_str}", parse_mode="Markdown", reply_markup=stop_kb)

        session.add(LectureScan(lecture_id=lid, student_id=student.id))
        participant.event_balance += lec.points
        session.commit()
        name = student.full_name
        new_balance = participant.event_balance
        points = lec.points
        tg_id = student.telegram_id
        lec_title = lec.title

    # Уведомление студенту
    if tg_id:
        try:
            await bot.send_message(
                tg_id,
                f"✅ Ты отмечен на лекции *{lec_title}*!\n+{points} б. → баланс мероприятия: {new_balance}",
                parse_mode="Markdown"
            )
        except Exception:
            pass

    scan_count = data.get("scan_count", 0) + 1
    await state.update_data(scan_count=scan_count)
    await message.answer(
        f"✅ *{name}* +{points} б. → {new_balance}\n_Всего: {scan_count}_",
        parse_mode="Markdown", reply_markup=stop_kb
    )


# ─────────────────────────────────────────────────────────────────────────────
#  РЕГИСТРАЦИЯ УЧАСТНИКОВ (со стартовыми баллами + уведомление)
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("scan_reg_"))
async def start_participant_scan(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔ Нет прав", show_alert=True)
    event_id = int(callback.data.split("_")[2])
    with Session() as session:
        event = session.query(Event).get(event_id)
        count = session.query(EventParticipant).filter_by(event_id=event_id).count()
        start_pts = event.points
        ev_title = event.title

    await state.update_data(event_id=event_id, reg_count=count, start_pts=start_pts, ev_title=ev_title)
    await state.set_state(EventScanState.REGISTER_PARTICIPANTS)

    stop_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏹ Остановить", callback_data="stop_reg_scan")]])
    await callback.message.answer(
        f"👥 *Регистрация участников*\n{ev_title}\nУже: {count}\nСтартовые баллы: {start_pts}\n\nСканируйте баркоды. /stop",
        parse_mode="Markdown", reply_markup=stop_kb
    )


@router.callback_query(F.data == "stop_reg_scan")
async def stop_reg_scan(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    event_id = data.get("event_id")
    count = data.get("reg_count", 0)
    await state.clear()
    await callback.message.answer(
        f"✅ Регистрация завершена. Участников: *{count}*", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="К мероприятию", callback_data=f"event_{event_id}")]])
    )


@router.message(EventScanState.REGISTER_PARTICIPANTS)
async def process_participant_registration(message: Message, state: FSMContext, bot: Bot):
    text_in = (message.text or "").strip()
    stop_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏹ Остановить", callback_data="stop_reg_scan")]])

    if text_in.lower() in ("/stop", "stop", "стоп"):
        data = await state.get_data()
        event_id = data.get("event_id")
        count = data.get("reg_count", 0)
        await state.clear()
        return await message.answer(
            f"✅ Готово. Участников: *{count}*", parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="К мероприятию", callback_data=f"event_{event_id}")]])
        )

    data = await state.get_data()
    event_id = data["event_id"]
    start_pts = data.get("start_pts", 0)
    ev_title = data.get("ev_title", "Мероприятие")

    with Session() as session:
        student = session.query(Student).filter_by(barcode=text_in).first()
        if not student:
            return await message.answer(f"❌ Баркод `{text_in}` не найден.", parse_mode="Markdown", reply_markup=stop_kb)

        existing = session.query(EventParticipant).filter_by(event_id=event_id, student_id=student.id).first()
        if existing:
            return await message.answer(f"🔁 *{student.full_name}* уже зарегистрирован.", parse_mode="Markdown", reply_markup=stop_kb)

        session.add(EventParticipant(event_id=event_id, student_id=student.id, event_balance=start_pts))
        session.commit()
        name = student.full_name
        tg_id = student.telegram_id

    # Уведомление студенту
    if tg_id:
        try:
            notif = f"✅ Ты зарегистрирован на *{ev_title}*!"
            if start_pts > 0:
                notif += f"\n🎁 Стартовые баллы: +{start_pts}"
            await bot.send_message(tg_id, notif, parse_mode="Markdown")
        except Exception:
            pass

    count = data.get("reg_count", 0) + 1
    await state.update_data(reg_count=count)
    pts_info = f" (+{start_pts} б.)" if start_pts > 0 else ""
    await message.answer(f"✅ *{name}* зарегистрирован{pts_info}\n_Всего: {count}_", parse_mode="Markdown", reply_markup=stop_kb)


# ─────────────────────────────────────────────────────────────────────────────
#  СПИСОК ОТСКАНИРОВАННЫХ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("scan_list_"))
async def scan_list(callback: CallbackQuery):
    lid = int(callback.data.split("_")[2])
    with Session() as session:
        lec = session.query(Lecture).get(lid)
        scans = session.query(LectureScan).filter_by(lecture_id=lid).order_by(LectureScan.scanned_at).all()
        rows = []
        for s in scans:
            student = session.query(Student).get(s.student_id)
            rows.append(f"{len(rows)+1}. {student.full_name} — {s.scanned_at.strftime('%H:%M')}")

    msg = f"📋 *{lec.title}* ({len(rows)} чел.):\n\n" + ("\n".join(rows) if rows else "Никого")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📷 Продолжить", callback_data=f"start_scan_{lid}")],
        [InlineKeyboardButton(text="⬅️ Назад",     callback_data=f"lecture_{lid}")],
    ])
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=kb)


# ─────────────────────────────────────────────────────────────────────────────
#  ПРИВЯЗКА ЗАДАНИЙ И ТОВАРОВ
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
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(f"📝 Задания *{event.title}*:", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("do_link_task_"))
async def do_link_task(callback: CallbackQuery):
    parts = callback.data.split("_")
    event_id, task_id = int(parts[3]), int(parts[4])
    with Session() as session:
        if not session.query(EventTask).filter_by(event_id=event_id, task_id=task_id).first():
            session.add(EventTask(event_id=event_id, task_id=task_id))
            session.commit()
    await callback.answer("✅ Привязано")
    callback.data = f"link_tasks_{event_id}"
    await link_tasks_page(callback)


@router.callback_query(F.data.startswith("unlink_task_"))
async def unlink_task(callback: CallbackQuery):
    parts = callback.data.split("_")
    event_id, task_id = int(parts[2]), int(parts[3])
    with Session() as session:
        et = session.query(EventTask).filter_by(event_id=event_id, task_id=task_id).first()
        if et: session.delete(et); session.commit()
    await callback.answer("🗑 Откреплено")
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
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(f"🛍 Товары *{event.title}*:", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("do_link_merch_"))
async def do_link_merch(callback: CallbackQuery):
    parts = callback.data.split("_")
    event_id, merch_id = int(parts[3]), int(parts[4])
    with Session() as session:
        if not session.query(EventMerch).filter_by(event_id=event_id, merch_id=merch_id).first():
            session.add(EventMerch(event_id=event_id, merch_id=merch_id))
            session.commit()
    await callback.answer("✅ Привязано")
    callback.data = f"link_merch_{event_id}"
    await link_merch_page(callback)


@router.callback_query(F.data.startswith("unlink_merch_"))
async def unlink_merch(callback: CallbackQuery):
    parts = callback.data.split("_")
    event_id, merch_id = int(parts[2]), int(parts[3])
    with Session() as session:
        em = session.query(EventMerch).filter_by(event_id=event_id, merch_id=merch_id).first()
        if em: session.delete(em); session.commit()
    await callback.answer("🗑 Откреплено")
    callback.data = f"link_merch_{event_id}"
    await link_merch_page(callback)


# ─────────────────────────────────────────────────────────────────────────────
#  ЗАДАНИЯ МЕРОПРИЯТИЯ (студент)
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("event_tasks_"))
async def event_tasks_page(callback: CallbackQuery):
    event_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        participant = session.query(EventParticipant).filter_by(event_id=event_id, student_id=student.id if student else -1).first() if student else None
        if not participant: return await callback.answer("❌ Ты не участник", show_alert=True)
        event = session.query(Event).get(event_id)
        linked = session.query(EventTask).filter_by(event_id=event_id).all()
        task_ids = [et.task_id for et in linked]
        tasks = session.query(Task).filter(Task.id.in_(task_ids), Task.is_deleted == False).all() if task_ids else []
        from models import TaskVerification
        verifs = {t.id: session.query(TaskVerification).filter_by(student_id=student.id, task_id=t.id).first() for t in tasks}
        balance = participant.event_balance

    buttons = []
    for t in tasks:
        v = verifs.get(t.id)
        emoji = "✅" if v and v.status == "approved" else ("⏳" if v and v.status == "pending" else "❌")
        buttons.append([InlineKeyboardButton(text=f"{emoji} {t.title} — {t.points} б.", callback_data=f"etask_{event_id}_{t.id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"event_{event_id}")])
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(
        f"📝 *{event.title}* — задания\n💰 Баллы: {balance}",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data.startswith("etask_"))
async def event_task_view(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    event_id, task_id = int(parts[1]), int(parts[2])
    user_id = callback.from_user.id
    with Session() as session:
        task = session.query(Task).get(task_id)
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        from models import TaskVerification
        verification = session.query(TaskVerification).filter_by(student_id=student.id if student else -1, task_id=task_id).first() if student else None

    msg = f"📌 *{task.title}*\n\n{task.description or ''}\n\n💯 {task.points} б.\n🔍 {'по ответу' if task.verification_type == 'auto' else 'по доказательству'}"
    buttons = []
    if verification and verification.status == "approved": msg += "\n\n✅ Выполнено"
    elif verification and verification.status == "pending": msg += "\n\n⏳ На проверке"
    else: buttons.append([InlineKeyboardButton(text="✍️ Выполнить", callback_data=f"do_etask_{event_id}_{task_id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"event_tasks_{event_id}")])
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("do_etask_"))
async def start_event_task(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    event_id, task_id = int(parts[2]), int(parts[3])
    with Session() as session:
        task = session.query(Task).get(task_id)
    await state.update_data(task_id=task_id, event_id=event_id, is_event_task=True)
    from states import TaskState
    if task.verification_type == "auto":
        await callback.message.answer("✏️ Введите ответ:")
        await state.set_state(TaskState.waiting_answer)
    else:
        await callback.message.answer(f"📤 {task.proof_text or 'Отправьте доказательство'}")
        await state.set_state(TaskState.waiting_proof)


# ─────────────────────────────────────────────────────────────────────────────
#  МАГАЗИН МЕРОПРИЯТИЯ (студент)
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("event_shop_"))
async def event_shop_page(callback: CallbackQuery):
    event_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        participant = session.query(EventParticipant).filter_by(event_id=event_id, student_id=student.id if student else -1).first() if student else None
        if not participant: return await callback.answer("❌ Ты не участник", show_alert=True)
        event = session.query(Event).get(event_id)
        merch_ids = [em.merch_id for em in session.query(EventMerch).filter_by(event_id=event_id).all()]
        items = session.query(Merchandise).filter(Merchandise.id.in_(merch_ids), Merchandise.is_deleted == False).all() if merch_ids else []
        from models import Purchase
        bought = {p.merch_id for p in session.query(Purchase).filter_by(student_id=student.id if student else -1).all()}
        balance = participant.event_balance

    buttons = []
    for item in items:
        emoji = "✅" if item.id in bought else ("🚫" if item.stock <= 0 else "🛒")
        buttons.append([InlineKeyboardButton(text=f"{emoji} {item.name} — {item.price} б.", callback_data=f"eshop_{event_id}_{item.id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"event_{event_id}")])
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(
        f"🛍 *{event.title}* — магазин\n💰 Баллы: {balance}",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data.startswith("eshop_"))
async def event_shop_item(callback: CallbackQuery):
    parts = callback.data.split("_")
    event_id, item_id = int(parts[1]), int(parts[2])
    user_id = callback.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        participant = session.query(EventParticipant).filter_by(event_id=event_id, student_id=student.id if student else -1).first()
        item = session.query(Merchandise).get(item_id)
        from models import Purchase
        already_bought = bool(session.query(Purchase).filter_by(student_id=student.id if student else -1, merch_id=item_id).first())

    if not item or not participant: return await callback.answer("Ошибка", show_alert=True)
    balance = participant.event_balance
    caption = f"🛍 *{item.name}*\n\n{item.description or ''}\n\n💰 {item.price} б.\n📦 {item.stock} шт.\n💳 Баланс: {balance}"

    buttons = []
    if already_bought: buttons.append([InlineKeyboardButton(text="✅ Уже куплено", callback_data="noop_shop")])
    elif item.stock <= 0: buttons.append([InlineKeyboardButton(text="🚫 Нет в наличии", callback_data="noop_shop")])
    elif balance >= item.price: buttons.append([InlineKeyboardButton(text="🛒 Купить", callback_data=f"ebuy_{event_id}_{item_id}")])
    else: buttons.append([InlineKeyboardButton(text="❌ Недостаточно", callback_data="noop_shop")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"event_shop_{event_id}")])

    try: await callback.message.delete()
    except Exception: pass
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    if item.photo_file_id:
        await callback.message.answer_photo(photo=item.photo_file_id, caption=caption, parse_mode="Markdown", reply_markup=kb)
    else:
        await callback.message.answer(caption, parse_mode="Markdown", reply_markup=kb)


@router.callback_query(F.data.startswith("ebuy_"))
async def event_buy(callback: CallbackQuery):
    parts = callback.data.split("_")
    event_id, item_id = int(parts[1]), int(parts[2])
    user_id = callback.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        participant = session.query(EventParticipant).filter_by(event_id=event_id, student_id=student.id if student else -1).first()
        item = session.query(Merchandise).get(item_id)
        from models import Purchase
        if not student or not participant or not item: return await callback.answer("Ошибка", show_alert=True)
        if participant.event_balance < item.price: return await callback.answer(f"❌ Нужно {item.price}, у тебя {participant.event_balance}", show_alert=True)
        if item.stock <= 0: return await callback.answer("❌ Закончился", show_alert=True)
        if session.query(Purchase).filter_by(student_id=student.id, merch_id=item_id).first(): return await callback.answer("❌ Уже куплено", show_alert=True)
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
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔ Нет прав", show_alert=True)
    event_id = int(callback.data.split("_")[2])
    with Session() as session:
        event = session.query(Event).get(event_id)
        count = session.query(EventParticipant).filter_by(event_id=event_id).count()
    await callback.message.answer(
        f"⚠️ Закрыть *{event.title}*?\nБаллы мероприятия сгорят у {count} участников.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Закрыть", callback_data=f"do_close_{event_id}"),
            InlineKeyboardButton(text="❌ Отмена",  callback_data=f"event_{event_id}"),
        ]])
    )


@router.callback_query(F.data.startswith("do_close_"))
async def do_close_event(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔ Нет прав", show_alert=True)
    event_id = int(callback.data.split("_")[2])
    with Session() as session:
        event = session.query(Event).get(event_id)
        event.status = 'closed'
        session.execute(text("UPDATE event_participants SET event_balance = 0 WHERE event_id=:eid"), {"eid": event_id})
        session.commit()
        title = event.title
    await callback.answer("🔴 Закрыто!", show_alert=True)
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(f"🔴 *{title}* закрыто.", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📥 К мероприятиям", callback_data="menu_events")]]))


@router.callback_query(F.data == "all_events_admin")
async def all_events_admin(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔ Нет прав", show_alert=True)
    with Session() as session:
        events = session.query(Event).order_by(Event.created_at.desc()).all()

    buttons = []
    for ev in events:
        icon = "🟢" if ev.status == 'active' else "🔴"
        lock = " 🔒" if ev.hidden else ""
        buttons.append([InlineKeyboardButton(text=f"{icon}{lock} {ev.title}", callback_data=f"event_{ev.id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_events")])
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer("📋 Все мероприятия:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
