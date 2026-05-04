# handlers/events.py
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import text

from database import Session
from models import (Event, EventParticipant, Lecture, LectureScan,
    Student, EventTask, EventMerch, Task, Merchandise, TaskVerification, Purchase)
from security import safe_int, rate_limited, validate_length, sanitize_text
from states import EventCreateState, LectureCreateState, EventScanState
from config import ADMIN_IDS

router = Router()


class EventEditState(StatesGroup):
    AWAITING_VALUE = State()
    AWAITING_IMAGE = State()


class EventTaskCreateState(StatesGroup):
    AWAITING_TITLE = State()
    AWAITING_DESCRIPTION = State()
    AWAITING_POINTS = State()
    AWAITING_CHECK_TYPE = State()
    AWAITING_CORRECT_ANSWER = State()
    AWAITING_PROOF_TEXT = State()


class EventMerchCreateState(StatesGroup):
    AWAITING_NAME = State()
    AWAITING_DESCRIPTION = State()
    AWAITING_PRICE = State()
    AWAITING_STOCK = State()
    AWAITING_IMAGE = State()


class EventMerchEditState(StatesGroup):
    AWAITING_STOCK = State()
    AWAITING_PRICE = State()


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
            my_event_ids = {p.event_id for p in session.query(EventParticipant).filter_by(student_id=student.id).all()}

        all_active = session.query(Event).filter_by(status='active').all()
        visible = [ev for ev in all_active if is_admin or ev.id in my_event_ids or not ev.hidden]

    buttons = []
    for ev in visible:
        mark = "✅ " if ev.id in my_event_ids else ""
        lock = "🔒 " if ev.hidden and is_admin else ""
        buttons.append([InlineKeyboardButton(text=f"{mark}{lock}🎪 {ev.title}", callback_data=f"event_{ev.id}")])

    if is_admin:
        buttons.append([InlineKeyboardButton(text="➕ Создать мероприятие", callback_data="create_event")])
        buttons.append([InlineKeyboardButton(text="📋 Все мероприятия",     callback_data="all_events_admin")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_back")])

    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(
        "📥 Мероприятия:" if visible else "📥 Активных мероприятий пока нет.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


# ─────────────────────────────────────────────────────────────────────────────
#  СТРАНИЦА МЕРОПРИЯТИЯ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("event_") &
    ~F.data.startswith("event_task") & ~F.data.startswith("event_merch") &
    ~F.data.startswith("event_shop") & ~F.data.startswith("event_info") &
    ~F.data.startswith("event_support") & ~F.data.startswith("event_settings") &
    ~F.data.startswith("event_admin"))
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
        participant = session.query(EventParticipant).filter_by(
            event_id=event_id, student_id=student.id if student else -1
        ).first() if student else None

        lectures = session.query(Lecture).filter_by(event_id=event_id).all()
        tasks_done = lectures_attended = purchases_count = 0
        if participant and student:
            tasks_done = session.execute(text("""
                SELECT COUNT(*) FROM task_verifications tv
                JOIN event_tasks et ON et.task_id = tv.task_id
                WHERE tv.student_id=:sid AND et.event_id=:eid AND tv.status='approved'
            """), {"sid": student.id, "eid": event_id}).scalar()
            purchases_count = session.execute(text("""
                SELECT COUNT(*) FROM purchases p
                JOIN event_merch em ON em.merch_id = p.merch_id
                WHERE p.student_id=:sid AND em.event_id=:eid
            """), {"sid": student.id, "eid": event_id}).scalar()
            lectures_attended = session.execute(text("""
                SELECT COUNT(*) FROM lecture_scans ls
                JOIN lectures l ON l.id=ls.lecture_id
                WHERE ls.student_id=:sid AND l.event_id=:eid
            """), {"sid": student.id, "eid": event_id}).scalar()

    is_participant = participant is not None
    event_balance = participant.event_balance if participant else 0

    try: await callback.message.delete()
    except Exception: pass

    # ── Участник (все — и модераторы тоже если участвуют) ────────────────────
    if is_participant:
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
        buttons.append([InlineKeyboardButton(text="🆘 Помощь",                 callback_data=f"support_event_{event_id}")])
        if is_admin:
            buttons.append([InlineKeyboardButton(text="👨‍💼 Админ панель мероприятия", callback_data=f"event_admin_{event_id}")])
        buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_events")])

        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        if event.image_file_id:
            await callback.message.answer_photo(photo=event.image_file_id, caption=msg, parse_mode="Markdown", reply_markup=kb)
        else:
            await callback.message.answer(msg, parse_mode="Markdown", reply_markup=kb)
        return

    # ── Публичная страница (не участник) ─────────────────────────────────────
    msg = f"🎪 *{event.title}*\n\n"
    if event.description: msg += f"{event.description}\n\n"
    if event.event_date:  msg += f"📅 Дата: {event.event_date}\n"
    if event.how_to_join: msg += f"\n🚀 *Как попасть:*\n{event.how_to_join}\n"

    buttons = []
    if is_admin:
        buttons.append([InlineKeyboardButton(text="👨‍💼 Админ панель мероприятия", callback_data=f"event_admin_{event_id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_events")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    if event.image_file_id:
        await callback.message.answer_photo(photo=event.image_file_id, caption=msg, parse_mode="Markdown", reply_markup=kb)
    else:
        await callback.message.answer(msg, parse_mode="Markdown", reply_markup=kb)


# ─────────────────────────────────────────────────────────────────────────────
#  АДМИН ПАНЕЛЬ МЕРОПРИЯТИЯ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("event_admin_") &
    ~F.data.startswith("event_admin_tasks_") & ~F.data.startswith("event_admin_merch_"))
async def event_admin_page(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔ Нет прав", show_alert=True)
    event_id = safe_int(callback.data.split("_")[2] if len(callback.data.split("_")) > 2 else "0")

    with Session() as session:
        event = session.query(Event).get(event_id)
        if not event: return await callback.answer("Не найдено")
        participants_count = session.query(EventParticipant).filter_by(event_id=event_id).count()
        lectures = session.query(Lecture).filter_by(event_id=event_id).all()
        task_count = session.query(EventTask).filter_by(event_id=event_id).count()
        merch_count = session.query(EventMerch).filter_by(event_id=event_id).count()

    status_icon = "🟢" if event.status == 'active' else "🔴"
    vis = "🔒 Скрытое (только после скана)" if event.hidden else "👁 Открытое для всех"
    feats = []
    if event.has_lectures: feats.append("📚 Лекции")
    if event.has_tasks:    feats.append("📝 Задания")
    if event.has_shop:     feats.append("🛍 Магазин")
    if not feats:          feats.append("💰 Только баллы")

    msg = (
        f"👨‍💼 *Управление: {event.title}*\n\n"
        f"{status_icon} Статус: {'Активно' if event.status == 'active' else 'Закрыто'}\n"
        f"🔒 Видимость: {vis}\n"
        f"💰 Стартовые баллы: {event.points}\n\n"
        f"👥 Участников: {participants_count}\n"
        f"📚 Лекций: {len(lectures)}\n"
        f"📝 Заданий: {task_count}\n"
        f"🛍 Товаров: {merch_count}\n"
        f"Функции: {' | '.join(feats)}"
    )

    buttons = [
        [InlineKeyboardButton(text="👥 Регистрация участников",   callback_data=f"scan_reg_{event_id}")],
    ]
    if event.has_lectures:
        buttons.append([InlineKeyboardButton(text="📚 Лекции",            callback_data=f"lectures_{event_id}")])
    if event.has_tasks:
        buttons.append([InlineKeyboardButton(text="📝 Задания мероприятия",callback_data=f"event_admin_tasks_{event_id}")])
    if event.has_shop:
        buttons.append([InlineKeyboardButton(text="🛍 Товары мероприятия", callback_data=f"event_admin_merch_{event_id}")])

    buttons += [
        [InlineKeyboardButton(text="📊 Статистика заданий",      callback_data=f"event_task_stats_{event_id}")],
        [InlineKeyboardButton(text="📊 Статистика покупок",       callback_data=f"event_merch_stats_{event_id}")],
        [InlineKeyboardButton(text="🆘 Обращения мероприятия",    callback_data=f"event_support_admin_{event_id}")],
        [InlineKeyboardButton(text="⚙️ Настройки",               callback_data=f"event_settings_{event_id}")],
    ]
    if event.status == 'active':
        buttons.append([InlineKeyboardButton(text="🔴 Закрыть мероприятие", callback_data=f"close_event_{event_id}")])
    buttons.append([InlineKeyboardButton(text="🗑 Удалить мероприятие",    callback_data=f"delete_event_{event_id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад",                 callback_data=f"event_{event_id}")])

    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


# ─────────────────────────────────────────────────────────────────────────────
#  УПРАВЛЕНИЕ ЗАДАНИЯМИ МЕРОПРИЯТИЯ (admin)
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("event_admin_tasks_"))
async def event_admin_tasks(callback: CallbackQuery):
    event_id = safe_int(callback.data.split("_")[3] if len(callback.data.split("_")) > 3 else "0")
    with Session() as session:
        event = session.query(Event).get(event_id)
        linked = session.query(EventTask).filter_by(event_id=event_id).all()
        linked_ids = {et.task_id for et in linked}
        all_global = session.query(Task).filter_by(is_deleted=False, event_id=None).all()
        own_tasks = session.query(Task).filter_by(is_deleted=False, event_id=event_id).all()

    buttons = []
    # Собственные задания мероприятия
    if own_tasks:
        buttons.append([InlineKeyboardButton(text="── Задания мероприятия ──", callback_data="noop_task")])
        for t in own_tasks:
            buttons.append([InlineKeyboardButton(text=f"✏️ {t.title} ({t.points} б.)", callback_data=f"event_edit_task_{event_id}_{t.id}")])

    # Глобальные задания для привязки
    if all_global:
        buttons.append([InlineKeyboardButton(text="── Добавить из общих ──", callback_data="noop_task")])
        for t in all_global:
            mark = "✅ " if t.id in linked_ids else "➕ "
            cb = f"unlink_task_{event_id}_{t.id}" if t.id in linked_ids else f"do_link_task_{event_id}_{t.id}"
            buttons.append([InlineKeyboardButton(text=f"{mark}{t.title} ({t.points} б.)", callback_data=cb)])

    buttons.append([InlineKeyboardButton(text="➕ Создать новое задание",    callback_data=f"create_ev_task_{event_id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад",                  callback_data=f"event_admin_{event_id}")])

    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(
        f"📝 Задания *{event.title}*:", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data.startswith("create_ev_task_"))
async def create_event_task_start(callback: CallbackQuery, state: FSMContext):
    event_id = safe_int(callback.data.split("_")[3] if len(callback.data.split("_")) > 3 else "0")
    await state.update_data(ev_task_event_id=event_id)
    await state.set_state(EventTaskCreateState.AWAITING_TITLE)
    await callback.message.answer(
        "📝 Название задания:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"event_admin_tasks_{event_id}")]
        ])
    )


@router.message(EventTaskCreateState.AWAITING_TITLE)
async def ev_task_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await message.answer("📄 Описание:")
    await state.set_state(EventTaskCreateState.AWAITING_DESCRIPTION)


@router.message(EventTaskCreateState.AWAITING_DESCRIPTION)
async def ev_task_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await message.answer("💯 Баллы:")
    await state.set_state(EventTaskCreateState.AWAITING_POINTS)


@router.message(EventTaskCreateState.AWAITING_POINTS)
async def ev_task_points(message: Message, state: FSMContext):
    if not message.text.strip().isdigit(): return await message.answer("❗ Введите число")
    await state.update_data(points=int(message.text.strip()))
    await message.answer(
        "Тип проверки:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✏️ По ответу",        callback_data="ev_task_check_auto"),
            InlineKeyboardButton(text="📷 По доказательству", callback_data="ev_task_check_manual"),
        ]])
    )
    await state.set_state(EventTaskCreateState.AWAITING_CHECK_TYPE)


@router.callback_query(F.data == "ev_task_check_auto")
async def ev_task_check_auto(callback: CallbackQuery, state: FSMContext):
    await state.update_data(verification_type="auto")
    await callback.message.answer("✏️ Правильный ответ:")
    await state.set_state(EventTaskCreateState.AWAITING_CORRECT_ANSWER)


@router.callback_query(F.data == "ev_task_check_manual")
async def ev_task_check_manual(callback: CallbackQuery, state: FSMContext):
    await state.update_data(verification_type="manual")
    await callback.message.answer("📤 Подсказка для студента (что прислать):")
    await state.set_state(EventTaskCreateState.AWAITING_PROOF_TEXT)


@router.message(EventTaskCreateState.AWAITING_CORRECT_ANSWER)
async def ev_task_correct_answer(message: Message, state: FSMContext):
    await state.update_data(correct_answer=message.text.strip(), proof_text=None)
    await _finish_ev_task(message, state)


@router.message(EventTaskCreateState.AWAITING_PROOF_TEXT)
async def ev_task_proof_text(message: Message, state: FSMContext):
    await state.update_data(proof_text=message.text.strip(), correct_answer=None)
    await _finish_ev_task(message, state)


async def _finish_ev_task(message: Message, state: FSMContext):
    data = await state.get_data()
    event_id = data["ev_task_event_id"]
    with Session() as session:
        task = Task(
            title=data["title"], description=data["description"],
            points=data["points"], verification_type=data["verification_type"],
            correct_answer=data.get("correct_answer"), proof_text=data.get("proof_text"),
            event_id=event_id
        )
        session.add(task)
        session.flush()
        session.add(EventTask(event_id=event_id, task_id=task.id))
        session.commit()
    await state.clear()
    await message.answer("✅ Задание создано!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 К заданиям", callback_data=f"event_admin_tasks_{event_id}")]
    ]))


@router.callback_query(F.data.startswith("event_edit_task_"))
async def event_edit_task_menu(callback: CallbackQuery):
    parts = callback.data.split("_")
    event_id, task_id = int(parts[3]), int(parts[4])
    with Session() as session:
        task = session.query(Task).get(task_id)

    await callback.message.answer(
        f"✏️ *{task.title}*\n💯 {task.points} б.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Удалить задание", callback_data=f"del_ev_task_{event_id}_{task_id}")],
            [InlineKeyboardButton(text="⬅️ Назад",          callback_data=f"event_admin_tasks_{event_id}")],
        ])
    )


@router.callback_query(F.data.startswith("del_ev_task_"))
async def del_ev_task(callback: CallbackQuery):
    parts = callback.data.split("_")
    event_id, task_id = int(parts[3]), int(parts[4])
    with Session() as session:
        session.execute(text("DELETE FROM event_tasks WHERE event_id=:eid AND task_id=:tid"), {"eid": event_id, "tid": task_id})
        session.execute(text("UPDATE tasks SET is_deleted=TRUE WHERE id=:id AND event_id=:eid"), {"id": task_id, "eid": event_id})
        session.commit()
    await callback.answer("🗑 Удалено")
    callback.data = f"event_admin_tasks_{event_id}"
    await event_admin_tasks(callback)


@router.callback_query(F.data.startswith("do_link_task_"))
async def do_link_task(callback: CallbackQuery):
    parts = callback.data.split("_"); event_id, task_id = int(parts[3]), int(parts[4])
    with Session() as session:
        if not session.query(EventTask).filter_by(event_id=event_id, task_id=task_id).first():
            session.add(EventTask(event_id=event_id, task_id=task_id)); session.commit()
    await callback.answer("✅ Привязано")
    callback.data = f"event_admin_tasks_{event_id}"
    await event_admin_tasks(callback)


@router.callback_query(F.data.startswith("unlink_task_"))
async def unlink_task(callback: CallbackQuery):
    parts = callback.data.split("_"); event_id, task_id = int(parts[2]), int(parts[3])
    with Session() as session:
        et = session.query(EventTask).filter_by(event_id=event_id, task_id=task_id).first()
        if et: session.delete(et); session.commit()
    await callback.answer("🗑 Откреплено")
    callback.data = f"event_admin_tasks_{event_id}"
    await event_admin_tasks(callback)


# ─────────────────────────────────────────────────────────────────────────────
#  УПРАВЛЕНИЕ ТОВАРАМИ МЕРОПРИЯТИЯ (admin)
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("event_admin_merch_"))
async def event_admin_merch(callback: CallbackQuery):
    event_id = safe_int(callback.data.split("_")[3] if len(callback.data.split("_")) > 3 else "0")
    with Session() as session:
        event = session.query(Event).get(event_id)
        linked = session.query(EventMerch).filter_by(event_id=event_id).all()
        linked_ids = {em.merch_id for em in linked}
        all_global = session.query(Merchandise).filter_by(is_deleted=False, event_id=None).all()
        own_merch_ids = [em.merch_id for em in linked
                         if session.query(Merchandise).get(em.merch_id) and
                            session.query(Merchandise).get(em.merch_id).event_id == event_id]
        own_merch = session.query(Merchandise).filter_by(is_deleted=False, event_id=event_id).all()

    buttons = []
    # Собственные товары мероприятия
    if own_merch:
        buttons.append([InlineKeyboardButton(text="── Товары мероприятия ──", callback_data="noop_shop")])
        for m in own_merch:
            buttons.append([InlineKeyboardButton(text=f"✏️ {m.name} ({m.price} б., {m.stock} шт.)",
                callback_data=f"event_edit_merch_{event_id}_{m.id}")])

    # Глобальные товары
    if all_global:
        buttons.append([InlineKeyboardButton(text="── Добавить из общих ──", callback_data="noop_shop")])
        for m in all_global:
            if m.id in linked_ids:
                em = next((x for x in linked if x.merch_id == m.id), None)
                stock_info = f"{em.custom_stock or m.stock} шт." if em else f"{m.stock} шт."
                price_info = f"{em.custom_price or m.price} б."
                buttons.append([InlineKeyboardButton(
                    text=f"✅ {m.name} ({price_info}, {stock_info})",
                    callback_data=f"ev_merch_edit_link_{event_id}_{m.id}"
                )])
            else:
                buttons.append([InlineKeyboardButton(
                    text=f"➕ {m.name} ({m.price} б.)",
                    callback_data=f"do_link_merch_{event_id}_{m.id}"
                )])

    buttons.append([InlineKeyboardButton(text="➕ Создать новый товар",  callback_data=f"create_ev_merch_{event_id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад",              callback_data=f"event_admin_{event_id}")])

    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(
        f"🛍 Товары *{event.title}*:", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data.startswith("ev_merch_edit_link_"))
async def ev_merch_edit_link(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_"); event_id, merch_id = int(parts[4]), int(parts[5])
    with Session() as session:
        em = session.query(EventMerch).filter_by(event_id=event_id, merch_id=merch_id).first()
        m = session.query(Merchandise).get(merch_id)
        cur_stock = em.custom_stock or m.stock
        cur_price = em.custom_price or m.price

    await state.update_data(ev_merch_event_id=event_id, ev_merch_id=merch_id)
    await callback.message.answer(
        f"✏️ *{m.name}*\nТекущие: {cur_price} б., {cur_stock} шт.\n\nВведите новую цену (или «-» чтобы не менять):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"event_admin_merch_{event_id}")]
        ])
    )
    await state.set_state(EventMerchEditState.AWAITING_PRICE)


@router.message(EventMerchEditState.AWAITING_PRICE)
async def ev_merch_edit_price(message: Message, state: FSMContext):
    val = message.text.strip()
    if val != "-" and not val.isdigit(): return await message.answer("❗ Введите число или «-»")
    await state.update_data(new_price=None if val == "-" else int(val))
    await message.answer("Введите новое количество (или «-» чтобы не менять):")
    await state.set_state(EventMerchEditState.AWAITING_STOCK)


@router.message(EventMerchEditState.AWAITING_STOCK)
async def ev_merch_edit_stock(message: Message, state: FSMContext):
    val = message.text.strip()
    if val != "-" and not val.isdigit(): return await message.answer("❗ Введите число или «-»")
    data = await state.get_data()
    event_id = data["ev_merch_event_id"]; merch_id = data["ev_merch_id"]
    new_price = data.get("new_price"); new_stock = None if val == "-" else int(val)

    with Session() as session:
        em = session.query(EventMerch).filter_by(event_id=event_id, merch_id=merch_id).first()
        if em:
            if new_price is not None: em.custom_price = new_price
            if new_stock is not None: em.custom_stock = new_stock
            session.commit()
    await state.clear()
    await message.answer("✅ Обновлено!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 К товарам", callback_data=f"event_admin_merch_{event_id}")]
    ]))


@router.callback_query(F.data.startswith("event_edit_merch_"))
async def event_edit_own_merch(callback: CallbackQuery):
    parts = callback.data.split("_"); event_id, merch_id = int(parts[3]), int(parts[4])
    with Session() as session:
        m = session.query(Merchandise).get(merch_id)
    await callback.message.answer(
        f"✏️ *{m.name}*\n💰 {m.price} б. | 📦 {m.stock} шт.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del_ev_merch_{event_id}_{merch_id}")],
            [InlineKeyboardButton(text="⬅️ Назад",  callback_data=f"event_admin_merch_{event_id}")],
        ])
    )


@router.callback_query(F.data.startswith("del_ev_merch_"))
async def del_ev_merch(callback: CallbackQuery):
    parts = callback.data.split("_"); event_id, merch_id = int(parts[3]), int(parts[4])
    with Session() as session:
        session.execute(text("DELETE FROM event_merch WHERE event_id=:eid AND merch_id=:mid"), {"eid": event_id, "mid": merch_id})
        session.execute(text("UPDATE merchandise SET is_deleted=TRUE WHERE id=:id AND event_id=:eid"), {"id": merch_id, "eid": event_id})
        session.commit()
    await callback.answer("🗑 Удалено")
    callback.data = f"event_admin_merch_{event_id}"
    await event_admin_merch(callback)


@router.callback_query(F.data.startswith("do_link_merch_"))
async def do_link_merch(callback: CallbackQuery):
    parts = callback.data.split("_"); event_id, merch_id = int(parts[3]), int(parts[4])
    with Session() as session:
        if not session.query(EventMerch).filter_by(event_id=event_id, merch_id=merch_id).first():
            session.add(EventMerch(event_id=event_id, merch_id=merch_id)); session.commit()
    await callback.answer("✅ Привязано")
    callback.data = f"event_admin_merch_{event_id}"
    await event_admin_merch(callback)


@router.callback_query(F.data.startswith("unlink_merch_"))
async def unlink_merch(callback: CallbackQuery):
    parts = callback.data.split("_"); event_id, merch_id = int(parts[2]), int(parts[3])
    with Session() as session:
        em = session.query(EventMerch).filter_by(event_id=event_id, merch_id=merch_id).first()
        if em: session.delete(em); session.commit()
    await callback.answer("🗑 Откреплено")
    callback.data = f"event_admin_merch_{event_id}"
    await event_admin_merch(callback)


@router.callback_query(F.data.startswith("create_ev_merch_"))
async def create_ev_merch_start(callback: CallbackQuery, state: FSMContext):
    event_id = safe_int(callback.data.split("_")[3] if len(callback.data.split("_")) > 3 else "0")
    await state.update_data(ev_merch_event_id=event_id)
    await state.set_state(EventMerchCreateState.AWAITING_NAME)
    await callback.message.answer(
        "📛 Название товара:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"event_admin_merch_{event_id}")]
        ])
    )


@router.message(EventMerchCreateState.AWAITING_NAME)
async def ev_merch_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("📄 Описание:"); await state.set_state(EventMerchCreateState.AWAITING_DESCRIPTION)


@router.message(EventMerchCreateState.AWAITING_DESCRIPTION)
async def ev_merch_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await message.answer("💰 Цена в баллах:"); await state.set_state(EventMerchCreateState.AWAITING_PRICE)


@router.message(EventMerchCreateState.AWAITING_PRICE)
async def ev_merch_price(message: Message, state: FSMContext):
    if not message.text.strip().isdigit(): return await message.answer("❗ Число")
    await state.update_data(price=int(message.text.strip()))
    await message.answer("📦 Количество:"); await state.set_state(EventMerchCreateState.AWAITING_STOCK)


@router.message(EventMerchCreateState.AWAITING_STOCK)
async def ev_merch_stock(message: Message, state: FSMContext):
    if not message.text.strip().isdigit(): return await message.answer("❗ Число")
    await state.update_data(stock=int(message.text.strip()))
    await message.answer("🖼 Фото (или «нет»):"); await state.set_state(EventMerchCreateState.AWAITING_IMAGE)


@router.message(EventMerchCreateState.AWAITING_IMAGE, F.photo)
async def ev_merch_image(message: Message, state: FSMContext):
    await state.update_data(photo_file_id=message.photo[-1].file_id)
    await _finish_ev_merch(message, state)


@router.message(EventMerchCreateState.AWAITING_IMAGE)
async def ev_merch_no_image(message: Message, state: FSMContext):
    await state.update_data(photo_file_id=None)
    await _finish_ev_merch(message, state)


async def _finish_ev_merch(message: Message, state: FSMContext):
    data = await state.get_data()
    event_id = data["ev_merch_event_id"]
    with Session() as session:
        # Сбрасываем sequence на случай десинхронизации после прямого SQL-импорта
        try:
            session.execute(text(
                "SELECT setval(pg_get_serial_sequence('merchandise', 'id'), "
                "COALESCE((SELECT MAX(id) FROM merchandise), 1))"
            ))
        except Exception:
            pass
        m = Merchandise(
            name=data["name"], description=data["description"],
            price=data["price"], stock=data["stock"],
            photo_file_id=data.get("photo_file_id"),
            event_id=event_id
        )
        session.add(m); session.flush()
        session.add(EventMerch(event_id=event_id, merch_id=m.id))
        session.commit()
    await state.clear()
    await message.answer("✅ Товар создан!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 К товарам", callback_data=f"event_admin_merch_{event_id}")]
    ]))


# ─────────────────────────────────────────────────────────────────────────────
#  СТАТИСТИКА МЕРОПРИЯТИЯ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("event_task_stats_"))
async def event_task_stats(callback: CallbackQuery):
    event_id = safe_int(callback.data.split("_")[3] if len(callback.data.split("_")) > 3 else "0")
    with Session() as session:
        event = session.query(Event).get(event_id)
        linked = session.query(EventTask).filter_by(event_id=event_id).all()
        task_ids = [et.task_id for et in linked]
        total = session.execute(text("""
            SELECT COUNT(*) FROM task_verifications tv
            WHERE tv.task_id = ANY(:ids) AND tv.status='approved'
        """), {"ids": task_ids}).scalar() if task_ids else 0

        rows = []
        for tid in task_ids:
            task = session.query(Task).get(tid)
            count = session.execute(text("""
                SELECT COUNT(*) FROM task_verifications WHERE task_id=:id AND status='approved'
            """), {"id": tid}).scalar()
            rows.append(f"📌 {task.title}: {count} чел.")

    msg = f"📊 *Статистика заданий — {event.title}*\n\nВсего выполнено: {total}\n\n" + ("\n".join(rows) if rows else "Нет заданий")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"event_admin_{event_id}")]])
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=kb)


@router.callback_query(F.data.startswith("event_merch_stats_"))
async def event_merch_stats(callback: CallbackQuery):
    event_id = safe_int(callback.data.split("_")[3] if len(callback.data.split("_")) > 3 else "0")
    with Session() as session:
        event = session.query(Event).get(event_id)
        linked = session.query(EventMerch).filter_by(event_id=event_id).all()
        merch_ids = [em.merch_id for em in linked]
        total = session.execute(text("""
            SELECT COUNT(*) FROM purchases WHERE merch_id = ANY(:ids)
        """), {"ids": merch_ids}).scalar() if merch_ids else 0

        rows = []
        for mid in merch_ids:
            m = session.query(Merchandise).get(mid)
            count = session.execute(text("SELECT COUNT(*) FROM purchases WHERE merch_id=:id"), {"id": mid}).scalar()
            rows.append(f"🛍 {m.name}: {count} куплено")

    msg = f"📊 *Статистика покупок — {event.title}*\n\nВсего покупок: {total}\n\n" + ("\n".join(rows) if rows else "Нет товаров")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"event_admin_{event_id}")]])
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=kb)


# ─────────────────────────────────────────────────────────────────────────────
#  НАСТРОЙКИ МЕРОПРИЯТИЯ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("event_settings_"))
async def event_settings(callback: CallbackQuery):
    event_id = safe_int(callback.data.split("_")[2] if len(callback.data.split("_")) > 2 else "0")
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔ Нет прав", show_alert=True)
    with Session() as session:
        event = session.query(Event).get(event_id)

    hl = "✅" if event.has_lectures else "❌"
    ht = "✅" if event.has_tasks else "❌"
    hs = "✅" if event.has_shop else "❌"

    buttons = [
        [
            InlineKeyboardButton(text=f"{hl} Лекции",  callback_data=f"toggle_feat_{event_id}_lectures"),
            InlineKeyboardButton(text=f"{ht} Задания", callback_data=f"toggle_feat_{event_id}_tasks"),
            InlineKeyboardButton(text=f"{hs} Магазин", callback_data=f"toggle_feat_{event_id}_shop"),
        ],
        [InlineKeyboardButton(text="🔒 Скрытое" if event.hidden else "👁 Открытое", callback_data=f"toggle_hidden_{event_id}")],
        [InlineKeyboardButton(text="✏️ Название",    callback_data=f"edit_ev_{event_id}_title")],
        [InlineKeyboardButton(text="💰 Баллы",        callback_data=f"edit_ev_{event_id}_points")],
        [InlineKeyboardButton(text="📅 Дата",         callback_data=f"edit_ev_{event_id}_event_date")],
        [InlineKeyboardButton(text="📝 Описание",     callback_data=f"edit_ev_{event_id}_description")],
        [InlineKeyboardButton(text="🚀 Как попасть",  callback_data=f"edit_ev_{event_id}_how_to_join")],
        [InlineKeyboardButton(text="📍 Место выдачи", callback_data=f"edit_ev_{event_id}_pickup_info")],
        [InlineKeyboardButton(text="🖼 Картинка",     callback_data=f"edit_ev_{event_id}_image")],
        [InlineKeyboardButton(text="⬅️ Назад",       callback_data=f"event_admin_{event_id}")],
    ]
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(f"⚙️ *Настройки: {event.title}*", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("toggle_feat_"))
async def toggle_feature(callback: CallbackQuery):
    parts = callback.data.split("_"); event_id = int(parts[2]); feature = parts[3]
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔ Нет прав", show_alert=True)
    field = {"lectures": "has_lectures", "tasks": "has_tasks", "shop": "has_shop"}.get(feature)
    if not field: return
    with Session() as session:
        event = session.query(Event).get(event_id)
        setattr(event, field, not getattr(event, field)); session.commit()
        new_val = getattr(event, field)
    await callback.answer(f"{'✅ Включено' if new_val else '❌ Отключено'}")
    callback.data = f"event_settings_{event_id}"
    await event_settings(callback)


@router.callback_query(F.data.startswith("toggle_hidden_"))
async def toggle_hidden(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔ Нет прав", show_alert=True)
    event_id = safe_int(callback.data.split("_")[2] if len(callback.data.split("_")) > 2 else "0")
    with Session() as session:
        event = session.query(Event).get(event_id)
        event.hidden = not event.hidden; session.commit()
        status = "скрытым 🔒" if event.hidden else "видимым 👁"
    await callback.answer(f"✅ {status}")
    callback.data = f"event_settings_{event_id}"
    await event_settings(callback)


@router.callback_query(F.data.startswith("edit_ev_"))
async def edit_event_field_start(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_", 3); event_id = int(parts[2]); field = parts[3]
    prompts = {
        "title":       "✏️ Новое название:",
        "points":      "💰 Новые стартовые баллы (число):",
        "event_date":  "📅 Новая дата (или «нет»):",
        "description": "📝 Новое описание (или «нет»):",
        "how_to_join": "🚀 Как попасть (или «нет»):",
        "pickup_info": "📍 Место выдачи товаров (или «нет» для сброса к адресу по умолчанию):\n\nПо умолчанию: Московский проспект 15, Главный корпус, Профком обучающихся, каб. И-108, пн–пт 8:00–17:00",
        "image":       "🖼 Отправьте новую картинку:",
    }
    await state.update_data(edit_event_id=event_id, edit_field=field)
    await state.set_state(EventEditState.AWAITING_IMAGE if field == "image" else EventEditState.AWAITING_VALUE)
    await callback.message.answer(
        prompts.get(field, "Введите значение:"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"event_settings_{event_id}")]
        ])
    )


@router.message(EventEditState.AWAITING_IMAGE, F.photo)
async def save_event_image(message: Message, state: FSMContext):
    data = await state.get_data(); event_id = data["edit_event_id"]
    with Session() as session:
        ev = session.query(Event).get(event_id)
        if ev: ev.image_file_id = message.photo[-1].file_id; session.commit()
    await state.clear()
    await message.answer("✅ Картинка обновлена!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data=f"event_settings_{event_id}")]
    ]))


@router.message(EventEditState.AWAITING_VALUE)
async def save_event_field(message: Message, state: FSMContext):
    data = await state.get_data(); field = data.get("edit_field"); event_id = data.get("edit_event_id")
    if not field or not event_id: await state.clear(); return
    value = message.text.strip() if message.text else ""; none_val = value.lower() == "нет"
    with Session() as session:
        ev = session.query(Event).get(event_id)
        if not ev: await state.clear(); return await message.answer("❌ Не найдено")
        if field == "points":
            if not value.isdigit(): return await message.answer("❗ Число")
            ev.points = int(value)
        elif field in ("event_date", "description", "how_to_join", "pickup_info"):
            setattr(ev, field, None if none_val else value)
        else:
            setattr(ev, field, value)
        session.commit()
    await state.clear()
    await message.answer("✅ Сохранено!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data=f"event_settings_{event_id}")]
    ]))


# ─────────────────────────────────────────────────────────────────────────────
#  ИНФОРМАЦИЯ О МЕРОПРИЯТИИ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("event_info_"))
async def event_info(callback: CallbackQuery):
    event_id = safe_int(callback.data.split("_")[2] if len(callback.data.split("_")) > 2 else "0")
    with Session() as session:
        event = session.query(Event).get(event_id)
    if not event: return await callback.answer("Не найдено")
    msg = f"ℹ️ *{event.title}*\n\n"
    if event.description: msg += f"{event.description}\n\n"
    if event.event_date:  msg += f"📅 Дата: {event.event_date}\n"
    if event.how_to_join: msg += f"\n🚀 Как попасть:\n{event.how_to_join}\n"
    if not (event.description or event.event_date or event.how_to_join):
        msg += "Дополнительная информация не добавлена."
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(msg, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"event_{event_id}")]]))


# ─────────────────────────────────────────────────────────────────────────────
#  СОЗДАНИЕ МЕРОПРИЯТИЯ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "create_event")
async def create_event_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔ Нет прав", show_alert=True)
    await callback.message.answer("🎪 Название мероприятия:")
    await state.set_state(EventCreateState.AWAITING_TITLE)


@router.message(EventCreateState.AWAITING_TITLE)
async def event_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await message.answer("💰 Стартовые баллы (или 0):")
    await state.set_state(EventCreateState.AWAITING_POINTS)


@router.message(EventCreateState.AWAITING_POINTS)
async def event_points(message: Message, state: FSMContext):
    if not message.text.strip().isdigit(): return await message.answer("❗ Число")
    await state.update_data(points=int(message.text.strip()))
    await message.answer("📅 Дата (или «нет»):"); await state.set_state(EventCreateState.AWAITING_DATE)


@router.message(EventCreateState.AWAITING_DATE)
async def event_date(message: Message, state: FSMContext):
    val = message.text.strip()
    await state.update_data(event_date=None if val.lower() == "нет" else val)
    await message.answer("📝 Описание (или «нет»):"); await state.set_state(EventCreateState.AWAITING_DESCRIPTION)


@router.message(EventCreateState.AWAITING_DESCRIPTION)
async def event_description(message: Message, state: FSMContext):
    val = message.text.strip()
    await state.update_data(description=None if val.lower() == "нет" else val)
    await message.answer("🖼 Картинка (фото или «нет»):"); await state.set_state(EventCreateState.AWAITING_IMAGE)


@router.message(EventCreateState.AWAITING_IMAGE, F.photo)
async def event_image(message: Message, state: FSMContext):
    await state.update_data(image_file_id=message.photo[-1].file_id)
    await _ask_how_to_join(message, state)


@router.message(EventCreateState.AWAITING_IMAGE)
async def event_no_image(message: Message, state: FSMContext):
    await state.update_data(image_file_id=None)
    await _ask_how_to_join(message, state)


async def _ask_how_to_join(message, state):
    await message.answer("🚀 Как попасть (или «нет»):")
    await state.set_state(EventCreateState.AWAITING_HOW_TO_JOIN)


@router.message(EventCreateState.AWAITING_HOW_TO_JOIN)
async def event_how_to_join(message: Message, state: FSMContext):
    val = message.text.strip()
    await state.update_data(how_to_join=None if val.lower() == "нет" else val)
    await _ask_pickup_info(message, state)


async def _ask_pickup_info(message, state):
    await message.answer(
        "📍 *Место выдачи товаров:*\n\n"
        "По умолчанию:\n"
        "_Московский проспект 15, Главный корпус, Профком обучающихся, каб. И-108, пн–пт 8:00–17:00_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Использовать по умолчанию", callback_data="ev_pickup_default")],
            [InlineKeyboardButton(text="✏️ Указать своё место",        callback_data="ev_pickup_custom")],
        ])
    )


@router.callback_query(F.data == "ev_pickup_default")
async def ev_pickup_default(callback: CallbackQuery, state: FSMContext):
    await state.update_data(pickup_info=None)
    await _ask_visibility(callback.message, state)


@router.callback_query(F.data == "ev_pickup_custom")
async def ev_pickup_custom(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "📍 Введите адрес:\n\n"
        "Пример: Московский проспект 15, Главный корпус, каб. И-108"
    )
    await state.set_state(EventCreateState.AWAITING_PICKUP_ADDRESS)


@router.message(EventCreateState.AWAITING_PICKUP_ADDRESS)
async def ev_pickup_address(message: Message, state: FSMContext):
    await state.update_data(pickup_address=message.text.strip())
    await message.answer(
        "🕐 Введите время выдачи:\n\n"
        "Пример: пн–пт, 8:00–17:00"
    )
    await state.set_state(EventCreateState.AWAITING_PICKUP_HOURS)


@router.message(EventCreateState.AWAITING_PICKUP_HOURS)
async def ev_pickup_hours(message: Message, state: FSMContext):
    data = await state.get_data()
    address = data.get("pickup_address", "")
    hours = message.text.strip()
    await state.update_data(pickup_info=f"{address}, {hours}")
    await _ask_visibility(message, state)


async def _ask_visibility(target, state):
    """target — Message или callback.message"""
    await target.answer(
        "Видимость:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👁 Открытое",               callback_data="ev_vis_0")],
            [InlineKeyboardButton(text="🔒 Скрытое (после скана)",  callback_data="ev_vis_1")],
        ])
    )
    await state.set_state(EventCreateState.AWAITING_HIDDEN)


@router.callback_query(F.data.startswith("ev_vis_"))
async def event_hidden_choice(callback: CallbackQuery, state: FSMContext):
    await state.update_data(hidden=callback.data == "ev_vis_1",
                            has_lectures=True, has_tasks=True, has_shop=True)
    await _show_features_choice(callback.message, state)
    await state.set_state(EventCreateState.AWAITING_FEATURES)


async def _show_features_choice(message, state):
    data = await state.get_data()
    hl = "✅" if data.get("has_lectures", True) else "❌"
    ht = "✅" if data.get("has_tasks", True) else "❌"
    hs = "✅" if data.get("has_shop", True) else "❌"
    await message.answer("Выберите функции:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"{hl} Лекции",  callback_data="ev_toggle_lectures"),
            InlineKeyboardButton(text=f"{ht} Задания", callback_data="ev_toggle_tasks"),
            InlineKeyboardButton(text=f"{hs} Магазин", callback_data="ev_toggle_shop"),
        ],
        [InlineKeyboardButton(text="✅ Создать мероприятие", callback_data="ev_feat_done")],
    ]))


@router.callback_query(F.data.startswith("ev_toggle_"))
async def ev_toggle_feature(callback: CallbackQuery, state: FSMContext):
    feat = callback.data.split("_")[2]; data = await state.get_data()
    await state.update_data(**{f"has_{feat}": not data.get(f"has_{feat}", True)})
    try: await callback.message.delete()
    except Exception: pass
    await _show_features_choice(callback.message, state)


@router.callback_query(F.data == "ev_feat_done")
async def event_features_done(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    with Session() as session:
        ev = Event(
            title=data["title"], points=data["points"],
            event_date=data.get("event_date"), description=data.get("description"),
            image_file_id=data.get("image_file_id"), how_to_join=data.get("how_to_join"),
            pickup_info=data.get("pickup_info"),
            hidden=data.get("hidden", False),
            has_lectures=data.get("has_lectures", True),
            has_tasks=data.get("has_tasks", True),
            has_shop=data.get("has_shop", True),
            status='active'
        )
        session.add(ev); session.commit(); event_id = ev.id; event_title = ev.title
    await state.clear()
    feats = []
    if data.get("has_lectures", True): feats.append("📚")
    if data.get("has_tasks", True):    feats.append("📝")
    if data.get("has_shop", True):     feats.append("🛍")
    if not feats:                      feats.append("💰")
    await callback.message.answer(
        f"✅ *{event_title}* создано! {' '.join(feats)}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Открыть", callback_data=f"event_{event_id}")]
        ])
    )


# ─────────────────────────────────────────────────────────────────────────────
#  ЛЕКЦИИ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("lectures_"))
async def lectures_list(callback: CallbackQuery):
    event_id = safe_int(callback.data.split("_")[1] if len(callback.data.split("_")) > 1 else "0")
    with Session() as session:
        event = session.query(Event).get(event_id)
        lectures = session.query(Lecture).filter_by(event_id=event_id).all()
    buttons = [[InlineKeyboardButton(text=f"📚 {l.title} ({l.points} б.)", callback_data=f"lecture_{l.id}")] for l in lectures]
    buttons.append([InlineKeyboardButton(text="➕ Добавить лекцию", callback_data=f"add_lecture_{event_id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад",          callback_data=f"event_admin_{event_id}")])
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(f"📚 Лекции — *{event.title}*:", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("add_lecture_"))
async def add_lecture_start(callback: CallbackQuery, state: FSMContext):
    event_id = safe_int(callback.data.split("_")[2] if len(callback.data.split("_")) > 2 else "0")
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
    lid = safe_int(callback.data.split("_")[1] if len(callback.data.split("_")) > 1 else "0")
    with Session() as session:
        lec = session.query(Lecture).get(lid)
        if not lec: return await callback.answer("Не найдена")
        scans_count = len(lec.scans); event_id = lec.event_id
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(f"📚 *{lec.title}*\n💰 {lec.points} б. | 👥 {scans_count}", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📷 Начать сканирование",  callback_data=f"start_scan_{lid}")],
            [InlineKeyboardButton(text="📋 Список",               callback_data=f"scan_list_{lid}")],
            [InlineKeyboardButton(text="🗑 Удалить",              callback_data=f"del_lecture_{lid}")],
            [InlineKeyboardButton(text="⬅️ Назад",               callback_data=f"lectures_{event_id}")],
        ]))


@router.callback_query(F.data.startswith("del_lecture_"))
async def del_lecture(callback: CallbackQuery):
    lid = safe_int(callback.data.split("_")[2] if len(callback.data.split("_")) > 2 else "0")
    with Session() as session:
        lec = session.query(Lecture).get(lid); event_id = lec.event_id if lec else None
        if lec:
            session.execute(text("DELETE FROM lecture_scans WHERE lecture_id=:id"), {"id": lid})
            session.delete(lec); session.commit()
    await callback.answer("🗑 Удалена")
    callback.data = f"lectures_{event_id}"; await lectures_list(callback)


# ─────────────────────────────────────────────────────────────────────────────
#  СКАНИРОВАНИЕ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("start_scan_"))
async def start_lecture_scan(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔ Нет прав", show_alert=True)
    lid = safe_int(callback.data.split("_")[2] if len(callback.data.split("_")) > 2 else "0")
    with Session() as session:
        lec = session.query(Lecture).get(lid)
        if not lec: return await callback.answer("Не найдена")
        lec_title, lec_points, event_id, scans_count = lec.title, lec.points, lec.event_id, len(lec.scans)
    await state.update_data(lecture_id=lid, event_id=event_id, scan_count=scans_count)
    await state.set_state(EventScanState.SCAN_LECTURE)
    stop_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏹ Остановить", callback_data="stop_scan")]])
    await callback.message.answer(
        f"📷 *{lec_title}* | {lec_points} б. | Уже: {scans_count}\n\nВводите баркод. /stop",
        parse_mode="Markdown", reply_markup=stop_kb)


@router.callback_query(F.data == "stop_scan")
async def stop_scan_btn(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data(); lid = data.get("lecture_id"); count = data.get("scan_count", 0)
    await state.clear()
    await callback.message.answer(f"✅ Завершено. Всего: *{count}*", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Список",    callback_data=f"scan_list_{lid}")],
            [InlineKeyboardButton(text="⬅️ К лекции", callback_data=f"lecture_{lid}")],
        ]))


@router.message(EventScanState.SCAN_LECTURE)
async def process_lecture_scan(message: Message, state: FSMContext, bot: Bot):
    text_in = (message.text or "").strip()
    stop_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏹ Остановить", callback_data="stop_scan")]])
    if text_in.lower() in ("/stop", "stop", "стоп"):
        data = await state.get_data(); lid = data.get("lecture_id"); count = data.get("scan_count", 0)
        await state.clear()
        return await message.answer(f"✅ Готово. Отсканировано: *{count}*", parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📋 Список", callback_data=f"scan_list_{lid}")]]))

    data = await state.get_data(); lid = data["lecture_id"]; event_id = data["event_id"]
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
            return await message.answer(f"🔁 *{student.full_name}* — уже в {existing.scanned_at.strftime('%H:%M')}", parse_mode="Markdown", reply_markup=stop_kb)
        session.add(LectureScan(lecture_id=lid, student_id=student.id))
        participant.event_balance += lec.points; session.commit()
        name = student.full_name; new_balance = participant.event_balance
        points = lec.points; tg_id = student.telegram_id; lec_title = lec.title

    if tg_id:
        try:
            await bot.send_message(tg_id,
                f"✅ Ты отмечен на лекции *{lec_title}*!\n+{points} б. → баланс: {new_balance}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🎪 К мероприятию", callback_data=f"event_{event_id}")]
                ]))
        except Exception: pass

    scan_count = data.get("scan_count", 0) + 1; await state.update_data(scan_count=scan_count)
    await message.answer(f"✅ *{name}* +{points} б. → {new_balance}\n_Всего: {scan_count}_",
        parse_mode="Markdown", reply_markup=stop_kb)


@router.callback_query(F.data.startswith("scan_reg_"))
async def start_participant_scan(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔ Нет прав", show_alert=True)
    event_id = safe_int(callback.data.split("_")[2] if len(callback.data.split("_")) > 2 else "0")
    with Session() as session:
        event = session.query(Event).get(event_id)
        count = session.query(EventParticipant).filter_by(event_id=event_id).count()
    await state.update_data(event_id=event_id, reg_count=count, start_pts=event.points, ev_title=event.title)
    await state.set_state(EventScanState.REGISTER_PARTICIPANTS)
    stop_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏹ Остановить", callback_data="stop_reg_scan")]])
    await callback.message.answer(
        f"👥 *{event.title}* | Уже: {count} | +{event.points} б.\n\nСканируйте. /stop",
        parse_mode="Markdown", reply_markup=stop_kb)


@router.callback_query(F.data == "stop_reg_scan")
async def stop_reg_scan(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data(); event_id = data.get("event_id"); count = data.get("reg_count", 0)
    await state.clear()
    await callback.message.answer(f"✅ Готово. Участников: *{count}*", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="К мероприятию", callback_data=f"event_{event_id}")]]))


@router.message(EventScanState.REGISTER_PARTICIPANTS)
async def process_participant_registration(message: Message, state: FSMContext, bot: Bot):
    text_in = (message.text or "").strip()
    stop_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏹ Остановить", callback_data="stop_reg_scan")]])
    if text_in.lower() in ("/stop", "stop", "стоп"):
        data = await state.get_data(); event_id = data.get("event_id"); count = data.get("reg_count", 0)
        await state.clear()
        return await message.answer(f"✅ Готово. Участников: *{count}*", parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="К мероприятию", callback_data=f"event_{event_id}")]]))

    data = await state.get_data(); event_id = data["event_id"]
    start_pts = data.get("start_pts", 0); ev_title = data.get("ev_title", "")

    with Session() as session:
        student = session.query(Student).filter_by(barcode=text_in).first()
        if not student:
            return await message.answer(f"❌ Баркод `{text_in}` не найден.", parse_mode="Markdown", reply_markup=stop_kb)
        existing = session.query(EventParticipant).filter_by(event_id=event_id, student_id=student.id).first()
        if existing:
            return await message.answer(f"🔁 *{student.full_name}* уже зарегистрирован.", parse_mode="Markdown", reply_markup=stop_kb)
        session.add(EventParticipant(event_id=event_id, student_id=student.id, event_balance=start_pts))
        session.commit(); name = student.full_name; tg_id = student.telegram_id

    if tg_id:
        try:
            notif = f"✅ Ты зарегистрирован на *{ev_title}*!"
            if start_pts > 0: notif += f"\n🎁 +{start_pts} стартовых баллов"
            await bot.send_message(tg_id, notif, parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🎪 К мероприятию", callback_data=f"event_{event_id}")]
                ]))
        except Exception: pass

    count = data.get("reg_count", 0) + 1; await state.update_data(reg_count=count)
    pts_info = f" (+{start_pts} б.)" if start_pts > 0 else ""
    await message.answer(f"✅ *{name}* зарегистрирован{pts_info}\n_Всего: {count}_",
        parse_mode="Markdown", reply_markup=stop_kb)


@router.callback_query(F.data.startswith("scan_list_"))
async def scan_list(callback: CallbackQuery):
    lid = safe_int(callback.data.split("_")[2] if len(callback.data.split("_")) > 2 else "0")
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
#  ЗАДАНИЯ МЕРОПРИЯТИЯ (студент)
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("event_tasks_"))
async def event_tasks_page(callback: CallbackQuery):
    event_id = safe_int(callback.data.split("_")[2] if len(callback.data.split("_")) > 2 else "0"); user_id = callback.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        participant = session.query(EventParticipant).filter_by(event_id=event_id, student_id=student.id if student else -1).first() if student else None
        if not participant: return await callback.answer("❌ Ты не участник", show_alert=True)
        event = session.query(Event).get(event_id)
        linked = session.query(EventTask).filter_by(event_id=event_id).all()
        task_ids = [et.task_id for et in linked]
        tasks = session.query(Task).filter(Task.id.in_(task_ids), Task.is_deleted == False).all() if task_ids else []
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
    await callback.message.answer(f"📝 *{event.title}*\n💰 Баллы: {balance}", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("etask_"))
async def event_task_view(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_"); event_id, task_id = int(parts[1]), int(parts[2])
    user_id = callback.from_user.id
    with Session() as session:
        task = session.query(Task).get(task_id)
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        verification = session.query(TaskVerification).filter_by(student_id=student.id if student else -1, task_id=task_id).first() if student else None
    msg = f"📌 *{task.title}*\n\n{task.description or ''}\n\n💯 {task.points} б."
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
    parts = callback.data.split("_"); event_id, task_id = int(parts[2]), int(parts[3])
    with Session() as session:
        task = session.query(Task).get(task_id)
    await state.update_data(task_id=task_id, event_id=event_id, is_event_task=True)
    from states import TaskState
    if task.verification_type == "auto":
        await callback.message.answer("✏️ Введите ответ:"); await state.set_state(TaskState.waiting_answer)
    else:
        await callback.message.answer(f"📤 {task.proof_text or 'Отправьте доказательство'}"); await state.set_state(TaskState.waiting_proof)


# ─────────────────────────────────────────────────────────────────────────────
#  МАГАЗИН МЕРОПРИЯТИЯ (студент)
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("event_shop_"))
async def event_shop_page(callback: CallbackQuery):
    event_id = safe_int(callback.data.split("_")[2] if len(callback.data.split("_")) > 2 else "0"); user_id = callback.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        participant = session.query(EventParticipant).filter_by(event_id=event_id, student_id=student.id if student else -1).first() if student else None
        if not participant: return await callback.answer("❌ Ты не участник", show_alert=True)
        event = session.query(Event).get(event_id)
        linked = session.query(EventMerch).filter_by(event_id=event_id).all()
        items = []
        for em in linked:
            m = session.query(Merchandise).get(em.merch_id)
            if m and not m.is_deleted:
                # Применяем кастомные цену/остаток
                if em.custom_price is not None: m.price = em.custom_price
                if em.custom_stock is not None: m.stock = em.custom_stock
                items.append(m)
        bought = {p.merch_id for p in session.query(Purchase).filter_by(student_id=student.id if student else -1).all()}
        balance = participant.event_balance
        pickup = getattr(event, 'pickup_info', None) or \
            "Московский проспект 15, Главный корпус, Профком обучающихся, каб. И-108 (пн–пт, 8:00–17:00)"

    buttons = []
    for item in items:
        emoji = "✅" if item.id in bought else ("🚫" if item.stock <= 0 else "🛒")
        buttons.append([InlineKeyboardButton(text=f"{emoji} {item.name} — {item.price} б.", callback_data=f"eshop_{event_id}_{item.id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"event_{event_id}")])
    try: await callback.message.delete()
    except Exception: pass
    shop_text = (
        f"🛍 *{event.title}*\n"
        f"💰 Баллы мероприятия: {balance}\n\n"
        f"📍 *Где получить:* {pickup}\n\n"
        f"ℹ️ Каждый товар можно купить только 1 раз."
    )
    await callback.message.answer(shop_text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("eshop_"))
async def event_shop_item(callback: CallbackQuery):
    parts = callback.data.split("_"); event_id, item_id = int(parts[1]), int(parts[2])
    user_id = callback.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        participant = session.query(EventParticipant).filter_by(event_id=event_id, student_id=student.id if student else -1).first()
        item = session.query(Merchandise).get(item_id)
        em = session.query(EventMerch).filter_by(event_id=event_id, merch_id=item_id).first()
        already_bought = bool(session.query(Purchase).filter_by(student_id=student.id if student else -1, merch_id=item_id).first())
        # Кастомные цена/остаток
        price = em.custom_price if em and em.custom_price else item.price
        stock = em.custom_stock if em and em.custom_stock is not None else item.stock

    if not item or not participant: return await callback.answer("Ошибка", show_alert=True)
    balance = participant.event_balance
    caption = f"🛍 *{item.name}*\n\n{item.description or ''}\n\n💰 {price} б.\n📦 {stock}\n💳 Баланс: {balance}"
    buttons = []
    if already_bought: buttons.append([InlineKeyboardButton(text="✅ Уже куплено", callback_data="noop_shop")])
    elif stock <= 0: buttons.append([InlineKeyboardButton(text="🚫 Нет", callback_data="noop_shop")])
    elif balance >= price: buttons.append([InlineKeyboardButton(text="🛒 Купить", callback_data=f"ebuy_{event_id}_{item_id}")])
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
    parts = callback.data.split("_"); event_id, item_id = int(parts[1]), int(parts[2])
    user_id = callback.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        participant = session.query(EventParticipant).filter_by(event_id=event_id, student_id=student.id if student else -1).first()
        item = session.query(Merchandise).get(item_id)
        em = session.query(EventMerch).filter_by(event_id=event_id, merch_id=item_id).first()
        price = em.custom_price if em and em.custom_price else item.price
        stock = em.custom_stock if em and em.custom_stock is not None else item.stock

        if not student or not participant or not item: return await callback.answer("Ошибка", show_alert=True)
        if participant.event_balance < price: return await callback.answer(f"❌ Нужно {price}, у тебя {participant.event_balance}", show_alert=True)
        if stock <= 0: return await callback.answer("❌ Закончился", show_alert=True)
        if session.query(Purchase).filter_by(student_id=student.id, merch_id=item_id).first(): return await callback.answer("❌ Уже куплено", show_alert=True)

        participant.event_balance -= price
        # Уменьшаем кастомный остаток если есть, иначе основной
        if em and em.custom_stock is not None:
            em.custom_stock -= 1
        else:
            item.stock -= 1
        session.add(Purchase(student_id=student.id, merch_id=item_id, quantity=1, total_points=price))
        session.commit(); item_name = item.name
    await callback.answer(f"✅ Куплено: {item_name}!", show_alert=True)


# ─────────────────────────────────────────────────────────────────────────────
#  ЗАКРЫТИЕ И УДАЛЕНИЕ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("close_event_"))
async def confirm_close_event(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔ Нет прав", show_alert=True)
    event_id = safe_int(callback.data.split("_")[2] if len(callback.data.split("_")) > 2 else "0")
    with Session() as session:
        event = session.query(Event).get(event_id)
        count = session.query(EventParticipant).filter_by(event_id=event_id).count()
    await callback.message.answer(
        f"⚠️ Закрыть *{event.title}*?\nБаллы сгорят у {count} участников.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Да", callback_data=f"do_close_{event_id}"),
            InlineKeyboardButton(text="❌ Нет", callback_data=f"event_admin_{event_id}"),
        ]]))


@router.callback_query(F.data.startswith("do_close_"))
async def do_close_event(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔ Нет прав", show_alert=True)
    event_id = safe_int(callback.data.split("_")[2] if len(callback.data.split("_")) > 2 else "0")
    with Session() as session:
        event = session.query(Event).get(event_id)
        event.status = 'closed'
        session.execute(text("UPDATE event_participants SET event_balance=0 WHERE event_id=:eid"), {"eid": event_id})
        session.commit(); title = event.title
    await callback.answer("🔴 Закрыто!", show_alert=True)
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(f"🔴 *{title}* закрыто.", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📥 К мероприятиям", callback_data="menu_events")]]))


@router.callback_query(F.data.startswith("delete_event_"))
async def confirm_delete_event(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔ Нет прав", show_alert=True)
    event_id = safe_int(callback.data.split("_")[2] if len(callback.data.split("_")) > 2 else "0")
    with Session() as session:
        event = session.query(Event).get(event_id)
    await callback.message.answer(
        f"⚠️ *Удалить мероприятие «{event.title}»?*\n\nВся информация (участники, лекции, статистика) будет удалена навсегда.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"do_delete_event_{event_id}"),
            InlineKeyboardButton(text="❌ Отмена",  callback_data=f"event_admin_{event_id}"),
        ]]))


@router.callback_query(F.data.startswith("do_delete_event_"))
async def do_delete_event(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔ Нет прав", show_alert=True)
    event_id = safe_int(callback.data.split("_")[3] if len(callback.data.split("_")) > 3 else "0")
    with Session() as session:
        # Удаляем в правильном порядке (FK constraints)
        session.execute(text("DELETE FROM lecture_scans WHERE lecture_id IN (SELECT id FROM lectures WHERE event_id=:eid)"), {"eid": event_id})
        session.execute(text("DELETE FROM lectures WHERE event_id=:eid"), {"eid": event_id})
        session.execute(text("DELETE FROM event_tasks WHERE event_id=:eid"), {"eid": event_id})
        session.execute(text("DELETE FROM event_merch WHERE event_id=:eid"), {"eid": event_id})
        session.execute(text("DELETE FROM event_participants WHERE event_id=:eid"), {"eid": event_id})
        session.execute(text("DELETE FROM support_tickets WHERE event_id=:eid"), {"eid": event_id})
        session.execute(text("UPDATE tasks SET is_deleted=TRUE WHERE event_id=:eid"), {"eid": event_id})
        session.execute(text("UPDATE merchandise SET is_deleted=TRUE WHERE event_id=:eid"), {"eid": event_id})
        session.execute(text("DELETE FROM events WHERE id=:eid"), {"eid": event_id})
        session.commit()
    await callback.answer("🗑 Мероприятие удалено!", show_alert=True)
    try: await callback.message.delete()
    except Exception: pass
    callback.data = "menu_events"; await events_menu(callback)


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
