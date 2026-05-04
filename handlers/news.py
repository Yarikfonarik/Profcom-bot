# handlers/news.py — Новости и рассылка
from aiogram import Router, F, Bot
from aiogram.types import (
    CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from sqlalchemy import text

from database import Session
from models import Student, EventParticipant, Event
from config import ADMIN_IDS
from security import safe_int, rate_limited, validate_length, sanitize_text

router = Router()


class NewsState(StatesGroup):
    AWAITING_TARGET   = State()   # кому отправить
    AWAITING_EVENT_ID = State()   # если по мероприятию
    AWAITING_CONTENT  = State()   # текст/фото/видео


# ─────────────────────────────────────────────────────────────────────────────
#  МЕНЮ НОВОСТЕЙ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "news_menu")
async def news_menu(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав", show_alert=True)
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(
        "📢 *Новости / Рассылка*\n\nВыберите получателей:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 Всем студентам",           callback_data="news_target_all")],
            [InlineKeyboardButton(text="🎪 Участникам мероприятия",   callback_data="news_target_event")],
            [InlineKeyboardButton(text="✅ Активным студентам",        callback_data="news_target_active")],
            [InlineKeyboardButton(text="⬅️ Назад",                   callback_data="admin_panel")],
        ])
    )


# ─────────────────────────────────────────────────────────────────────────────
#  ВЫБОР ЦЕЛИ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "news_target_all")
async def news_target_all(callback: CallbackQuery, state: FSMContext):
    await state.update_data(target="all")
    await _ask_content(callback.message, state)


@router.callback_query(F.data == "news_target_active")
async def news_target_active(callback: CallbackQuery, state: FSMContext):
    await state.update_data(target="active")
    await _ask_content(callback.message, state)


@router.callback_query(F.data == "news_target_event")
async def news_target_event(callback: CallbackQuery, state: FSMContext):
    with Session() as session:
        events = session.query(Event).filter_by(status='active').all()

    if not events:
        return await callback.answer("Нет активных мероприятий", show_alert=True)

    buttons = [[InlineKeyboardButton(text=f"🎪 {ev.title}", callback_data=f"news_ev_{ev.id}")] for ev in events]
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="news_menu")])
    await state.set_state(NewsState.AWAITING_EVENT_ID)
    await callback.message.answer(
        "Выберите мероприятие:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data.startswith("news_ev_"))
async def news_ev_selected(callback: CallbackQuery, state: FSMContext):
    event_id = safe_int(callback.data.split("_")[2] if len(callback.data.split("_")) > 2 else "0")
    with Session() as session:
        ev = session.query(Event).get(event_id)
        count = session.query(EventParticipant).filter_by(event_id=event_id).count()
    await state.update_data(target="event", event_id=event_id, event_title=ev.title)
    await _ask_content(callback.message, state,
        note=f"Получатели: участники *{ev.title}* ({count} чел.)")


async def _ask_content(message, state: FSMContext, note: str = ""):
    await state.set_state(NewsState.AWAITING_CONTENT)
    text = (
        "✏️ Напишите сообщение для рассылки.\n\n"
        "Можно отправить:\n• Текст\n• Фото с подписью\n• Видео с подписью\n\n"
    )
    if note:
        text += f"_{note}_\n\n"
    text += "После отправки рассылка начнётся немедленно."
    await message.answer(
        text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="news_menu")]
        ])
    )


# ─────────────────────────────────────────────────────────────────────────────
#  ПОЛУЧЕНИЕ КОНТЕНТА И РАССЫЛКА
# ─────────────────────────────────────────────────────────────────────────────

@router.message(NewsState.AWAITING_CONTENT)
async def send_news(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()

    target = data.get("target", "all")
    event_id = data.get("event_id")
    event_title = data.get("event_title", "")

    # Собираем список telegram_id получателей
    with Session() as session:
        if target == "event" and event_id:
            rows = session.execute(text("""
                SELECT s.telegram_id FROM event_participants ep
                JOIN students s ON s.id = ep.student_id
                WHERE ep.event_id = :eid AND s.telegram_id IS NOT NULL AND s.status = 'active'
            """), {"eid": event_id}).fetchall()
        elif target == "active":
            rows = session.execute(text(
                "SELECT telegram_id FROM students WHERE telegram_id IS NOT NULL AND status = 'active'"
            )).fetchall()
        else:  # all
            rows = session.execute(text(
                "SELECT telegram_id FROM students WHERE telegram_id IS NOT NULL"
            )).fetchall()

    recipients = [r[0] for r in rows]
    total = len(recipients)

    if total == 0:
        return await message.answer("❌ Нет получателей с привязанным Telegram.")

    target_label = {
        "all": "всем студентам",
        "active": "активным студентам",
        "event": f"участникам «{event_title}»"
    }.get(target, "всем")

    # Показываем превью
    preview_text = f"📢 Рассылка {target_label} ({total} чел.)"
    status_msg = await message.answer(f"⏳ Начинаю рассылку {target_label}...\nПолучателей: {total}")

    # Отправляем
    sent = 0; failed = 0
    for tg_id in recipients:
        try:
            if message.photo:
                await bot.send_photo(
                    tg_id, message.photo[-1].file_id,
                    caption=(message.caption or ""),
                )
            elif message.video:
                await bot.send_video(
                    tg_id, message.video.file_id,
                    caption=(message.caption or ""),
                )
            elif message.text:
                await bot.send_message(tg_id, message.text)
            sent += 1
        except Exception:
            failed += 1

        # Обновляем прогресс каждые 50 отправок
        if (sent + failed) % 50 == 0:
            try:
                await status_msg.edit_text(
                    f"⏳ Рассылка...\n✅ Отправлено: {sent}\n❌ Ошибок: {failed}"
                )
            except Exception:
                pass

    try:
        await status_msg.edit_text(
            f"✅ *Рассылка завершена!*\n\n"
            f"📤 Отправлено: {sent}\n"
            f"❌ Не доставлено: {failed}\n"
            f"👥 Всего: {total}",
            parse_mode="Markdown"
        )
    except Exception:
        await message.answer(f"✅ Рассылка завершена!\n✉️ {sent}/{total}")


# ─────────────────────────────────────────────────────────────────────────────
#  СТАТИСТИКА МЕРОПРИЯТИЙ (вызывается из раздела Статистика)
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "events_stats_menu")
async def events_stats_menu(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔ Нет прав", show_alert=True)
    with Session() as session:
        events = session.query(Event).order_by(Event.created_at.desc()).limit(20).all()

    buttons = []
    for ev in events:
        icon = "🟢" if ev.status == 'active' else "🔴"
        buttons.append([InlineKeyboardButton(text=f"{icon} {ev.title}", callback_data=f"ev_stat_{ev.id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="stats_menu")])

    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(
        "🎪 *Статистика мероприятий*\n\nВыберите мероприятие:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data.startswith("ev_stat_"))
async def ev_stat_detail(callback: CallbackQuery):
    event_id = safe_int(callback.data.split("_")[2] if len(callback.data.split("_")) > 2 else "0")
    with Session() as session:
        ev = session.query(Event).get(event_id)
        participants = session.execute(text(
            "SELECT COUNT(*) FROM event_participants WHERE event_id=:eid"
        ), {"eid": event_id}).scalar()
        total_balance = session.execute(text(
            "SELECT COALESCE(SUM(event_balance),0) FROM event_participants WHERE event_id=:eid"
        ), {"eid": event_id}).scalar()
        lectures_count = session.execute(text(
            "SELECT COUNT(*) FROM lectures WHERE event_id=:eid"
        ), {"eid": event_id}).scalar()
        scans_total = session.execute(text("""
            SELECT COUNT(*) FROM lecture_scans ls
            JOIN lectures l ON l.id = ls.lecture_id
            WHERE l.event_id=:eid
        """), {"eid": event_id}).scalar()
        tasks_done = session.execute(text("""
            SELECT COUNT(*) FROM task_verifications tv
            JOIN event_tasks et ON et.task_id = tv.task_id
            WHERE et.event_id=:eid AND tv.status='approved'
        """), {"eid": event_id}).scalar()
        purchases = session.execute(text("""
            SELECT COUNT(*) FROM purchases p
            JOIN event_merch em ON em.merch_id = p.merch_id
            WHERE em.event_id=:eid
        """), {"eid": event_id}).scalar()

    icon = "🟢" if ev.status == 'active' else "🔴"
    msg = (
        f"{icon} *{ev.title}*\n\n"
        f"👥 Участников: {participants}\n"
        f"💰 Баллов начислено: {total_balance}\n"
        f"📚 Лекций: {lectures_count}\n"
        f"🖊 Посещений лекций: {scans_total}\n"
        f"📝 Заданий выполнено: {tasks_done}\n"
        f"🛍 Покупок: {purchases}\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="events_stats_menu")]])
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=kb)
