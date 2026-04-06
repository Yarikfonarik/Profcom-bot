# handlers/support.py — чат-система с тикетами
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from database import Session
from models import Student, SupportTicket, SupportMessage
from config import ADMIN_IDS
from states import SupportState

router = Router()

# Активные чат-сессии: {user_id: ticket_id}
# Если пользователь в чате — сообщения идут напрямую в тикет без state
_active_chat: dict[int, int] = {}


def _get_mods(session) -> list[tuple[int, str]]:
    mods = session.query(Student).filter(
        Student.role.in_(["admin", "moderator"]),
        Student.telegram_id != None
    ).all()
    result = [(m.telegram_id, m.full_name) for m in mods]
    for a in ADMIN_IDS:
        if not any(r[0] == a for r in result):
            result.append((a, f"Администратор"))
    return result


def _chat_kb(ticket_id: int, is_mod: bool = False, event_id: int = None) -> InlineKeyboardMarkup:
    rows = []
    if is_mod:
        rows.append([InlineKeyboardButton(text="🔄 Передать", callback_data=f"transfer_choose_{ticket_id}")])
        rows.append([InlineKeyboardButton(text="✅ Закрыть тикет", callback_data=f"close_ticket_{ticket_id}")])
    rows.append([InlineKeyboardButton(text="🚪 Выйти из чата", callback_data=f"exit_chat_{ticket_id}")])
    if event_id:
        rows.append([InlineKeyboardButton(text="🎪 К мероприятию", callback_data=f"event_{event_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _enter_chat_kb(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Войти в чат", callback_data=f"enter_chat_{ticket_id}")]
    ])


async def _send_to_chat(message: Message, ticket_id: int, sender_id: int, bot: Bot,
                         text_content: str = None, file_id: str = None, file_type: str = None):
    """Сохраняет и доставляет сообщение в чате тикета."""
    with Session() as session:
        ticket = session.query(SupportTicket).get(ticket_id)
        if not ticket: return

        session.add(SupportMessage(
            ticket_id=ticket_id, sender_id=sender_id,
            text=text_content, file_id=file_id, file_type=file_type
        ))
        session.commit()

        student_tg = ticket.student_telegram_id
        mod_tg = ticket.moderator_telegram_id
        event_id = ticket.event_id if hasattr(ticket, 'event_id') else None

        student_obj = session.query(Student).filter_by(telegram_id=student_tg).first()
        student_name = student_obj.full_name if student_obj else f"ID:{student_tg}"
        mod_obj = session.query(Student).filter_by(telegram_id=mod_tg).first() if mod_tg else None
        mod_name = mod_obj.full_name if mod_obj else "Модератор"

    is_mod_sender = sender_id != student_tg
    sender_name = mod_name if is_mod_sender else student_name

    # Кому отправлять
    targets_student = [student_tg]
    with Session() as session:
        mods = _get_mods(session)
    mod_ids = [mod_tg] if mod_tg else [m[0] for m in mods]

    # Формируем сообщение
    header = f"{'🛡 ' + sender_name if is_mod_sender else '👤 ' + sender_name}:\n"

    async def _send_msg(target_id: int, is_target_mod: bool):
        if target_id == sender_id: return
        in_chat = _active_chat.get(target_id) == ticket_id
        kb = _chat_kb(ticket_id, is_mod=is_target_mod) if in_chat else _enter_chat_kb(ticket_id)
        notif_header = header if in_chat else f"🔔 Новое сообщение в тикете #{ticket_id} от {sender_name}:\nВойди в чат чтобы ответить."
        content = (text_content or "") if in_chat else ""

        try:
            if in_chat and file_id:
                if file_type == 'photo':
                    await bot.send_photo(target_id, file_id, caption=header + (text_content or ""), reply_markup=kb)
                elif file_type == 'video':
                    await bot.send_video(target_id, file_id, caption=header, reply_markup=kb)
                elif file_type == 'document':
                    await bot.send_document(target_id, file_id, caption=header, reply_markup=kb)
                elif file_type == 'voice':
                    await bot.send_voice(target_id, file_id, caption=header, reply_markup=kb)
            else:
                msg_text = (header + content) if in_chat else notif_header
                if msg_text:
                    await bot.send_message(target_id, msg_text, reply_markup=kb)
        except Exception:
            pass

    for mid in mod_ids:
        await _send_msg(mid, is_target_mod=True)
    for sid in targets_student:
        await _send_msg(sid, is_target_mod=False)


# ── Вход в чат ────────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("enter_chat_"))
async def enter_chat(callback: CallbackQuery, state: FSMContext):
    ticket_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id

    with Session() as session:
        ticket = session.query(SupportTicket).get(ticket_id)
        if not ticket: return await callback.answer("Тикет не найден")
        # Назначаем модератора если заходит модератор
        if user_id in ADMIN_IDS and not ticket.moderator_telegram_id:
            ticket.moderator_telegram_id = user_id
            session.commit()

        messages = session.query(SupportMessage).filter_by(ticket_id=ticket_id).order_by(SupportMessage.sent_at).all()
        student_tg = ticket.student_telegram_id
        event_id = getattr(ticket, 'event_id', None)

        history = []
        for sm in messages:
            is_mod = sm.sender_id != student_tg
            role = "🛡" if is_mod else "👤"
            student_obj = session.query(Student).filter_by(telegram_id=sm.sender_id).first()
            name = student_obj.full_name if student_obj else f"ID:{sm.sender_id}"
            ts = sm.sent_at.strftime("%H:%M")
            content = sm.text or f"[{sm.file_type}]"
            history.append(f"[{ts}] {role} {name}: {content}")

    _active_chat[user_id] = ticket_id
    await state.clear()

    is_mod = user_id in ADMIN_IDS
    history_text = "\n".join(history[-20:]) if history else "(история пуста)"

    await callback.message.answer(
        f"💬 *Чат тикет #{ticket_id}*\n\n{history_text}\n\n_Напишите сообщение — оно сразу уйдёт в чат._",
        parse_mode="Markdown",
        reply_markup=_chat_kb(ticket_id, is_mod=is_mod, event_id=event_id)
    )


@router.callback_query(F.data.startswith("exit_chat_"))
async def exit_chat(callback: CallbackQuery):
    user_id = callback.from_user.id
    _active_chat.pop(user_id, None)
    await callback.message.answer("🚪 Вышел из чата. Придёт уведомление если напишут.")
    try: await callback.message.delete()
    except Exception: pass


# ── Начало поддержки ─────────────────────────────────────────────────────────
async def _open_support(message: Message, state: FSMContext, user_id: int, event_id: int = None):
    await state.clear()
    with Session() as session:
        ticket = session.query(SupportTicket).filter_by(student_telegram_id=user_id, status='open').first()
        if not ticket:
            ticket = SupportTicket(student_telegram_id=user_id)
            if event_id:
                ticket.event_id = event_id
            session.add(ticket)
            session.commit()
        ticket_id = ticket.id

    _active_chat[user_id] = ticket_id
    await state.clear()

    event_note = f"\n🎪 _Обращение с мероприятия #{event_id}_" if event_id else ""
    await message.answer(
        f"💬 *Чат поддержки* #{ticket_id}{event_note}\n\nПишите сообщение — оно сразу уйдёт модератору.\nДля выхода нажмите кнопку ниже.",
        parse_mode="Markdown",
        reply_markup=_chat_kb(ticket_id, is_mod=False)
    )


@router.callback_query(F.data == "support")
async def support_start(callback: CallbackQuery, state: FSMContext):
    await _open_support(callback.message, state, callback.from_user.id)


@router.callback_query(F.data == "support_unreg")
async def support_unreg(callback: CallbackQuery, state: FSMContext):
    await _open_support(callback.message, state, callback.from_user.id)


@router.callback_query(F.data.startswith("support_event_"))
async def support_event(callback: CallbackQuery, state: FSMContext):
    event_id = int(callback.data.split("_")[2])
    await _open_support(callback.message, state, callback.from_user.id, event_id=event_id)


@router.callback_query(F.data == "cancel_support")
async def cancel_support(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    _active_chat.pop(callback.from_user.id, None)
    await callback.message.answer("Отменено.")


# ── Перехват всех сообщений для активных чатов ───────────────────────────────
# ВАЖНО: этот хендлер должен быть ПОСЛЕДНИМ в файле и использует низкий приоритет

@router.message(F.text | F.photo | F.document | F.voice | F.video)
async def handle_chat_message(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    ticket_id = _active_chat.get(user_id)
    if not ticket_id:
        return  # Не в чате — пропускаем

    # В чате — отправляем сообщение
    file_id, file_type = None, None
    if message.photo:     file_id = message.photo[-1].file_id; file_type = 'photo'
    elif message.document: file_id = message.document.file_id; file_type = 'document'
    elif message.voice:    file_id = message.voice.file_id;    file_type = 'voice'
    elif message.video:    file_id = message.video.file_id;    file_type = 'video'

    await _send_to_chat(
        message, ticket_id, user_id, bot,
        text_content=message.text or message.caption,
        file_id=file_id, file_type=file_type
    )


# ── Ответ из уведомления ──────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("reply_ticket_"))
async def reply_to_ticket(callback: CallbackQuery):
    ticket_id = int(callback.data.split("_")[2])
    callback.data = f"enter_chat_{ticket_id}"
    await enter_chat(callback, FSMContext.__new__(FSMContext))


@router.callback_query(F.data.startswith("student_reply_"))
async def student_reply_start(callback: CallbackQuery, state: FSMContext):
    ticket_id = int(callback.data.split("_")[2])
    callback.data = f"enter_chat_{ticket_id}"
    await enter_chat(callback, state)


# ── Передача тикета ──────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("transfer_choose_"))
async def transfer_choose(callback: CallbackQuery):
    ticket_id = int(callback.data.split("_")[2])
    sender_id = callback.from_user.id

    with Session() as session:
        mods = _get_mods(session)

    buttons = []
    for mod_tg_id, mod_name in mods:
        if mod_tg_id != sender_id:
            buttons.append([InlineKeyboardButton(
                text=f"👤 {mod_name}",
                callback_data=f"do_transfer_{ticket_id}_{mod_tg_id}"
            )])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data=f"enter_chat_{ticket_id}")])

    if not buttons[:-1]:
        return await callback.answer("Нет других модераторов", show_alert=True)

    await callback.message.answer(
        "Выберите модератора:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data.startswith("do_transfer_"))
async def do_transfer_ticket(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split("_")
    ticket_id, new_mod_id = int(parts[2]), int(parts[3])
    sender_id = callback.from_user.id

    with Session() as session:
        ticket = session.query(SupportTicket).get(ticket_id)
        if not ticket: return await callback.answer("Тикет не найден")
        messages = session.query(SupportMessage).filter_by(ticket_id=ticket_id).order_by(SupportMessage.sent_at).all()
        student_tg = ticket.student_telegram_id
        history = "\n".join(
            f"[{sm.sent_at.strftime('%H:%M')}] {'Мод' if sm.sender_id != student_tg else 'Студент'}: {sm.text or f'[{sm.file_type}]'}"
            for sm in messages
        )
        ticket.moderator_telegram_id = new_mod_id
        session.commit()

    _active_chat.pop(sender_id, None)
    try:
        await bot.send_message(
            new_mod_id,
            f"🔄 *Тикет #{ticket_id} передан вам*\n\n*История:*\n{history or '(пусто)'}",
            parse_mode="Markdown",
            reply_markup=_enter_chat_kb(ticket_id)
        )
    except Exception: pass

    await callback.answer("✅ Тикет передан", show_alert=True)
    try: await callback.message.delete()
    except Exception: pass


# ── Закрытие тикета ────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("close_ticket_"))
async def close_ticket(callback: CallbackQuery, bot: Bot):
    ticket_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    with Session() as session:
        ticket = session.query(SupportTicket).get(ticket_id)
        if ticket:
            ticket.status = 'closed'
            session.commit()
            student_tg = ticket.student_telegram_id

    _active_chat.pop(user_id, None)
    try:
        await bot.send_message(student_tg, f"✅ Тикет #{ticket_id} закрыт модератором.")
    except Exception: pass

    await callback.answer("✅ Тикет закрыт")
    try: await callback.message.delete()
    except Exception: pass


# ── Панель обращений (админ) ──────────────────────────────────────────────────
@router.callback_query(F.data == "support_admin")
async def support_admin(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔ Нет прав", show_alert=True)

    with Session() as session:
        open_tickets = session.query(SupportTicket).filter_by(status='open').order_by(SupportTicket.created_at.desc()).all()
        closed_count = session.query(SupportTicket).filter_by(status='closed').count()

        unanswered, answered = [], []
        for t in open_tickets:
            has_reply = session.query(SupportMessage).filter(
                SupportMessage.ticket_id == t.id,
                SupportMessage.sender_id != t.student_telegram_id
            ).first() is not None
            student = session.query(Student).filter_by(telegram_id=t.student_telegram_id).first()
            name = student.full_name if student else f"ID:{t.student_telegram_id}"
            event_note = f" [🎪]" if getattr(t, 'event_id', None) else ""
            info = (t.id, name + event_note, has_reply)
            (answered if has_reply else unanswered).append(info)

    msg = f"🆘 *Обращения*\n\n❗ Без ответа: {len(unanswered)} | 📋 С ответом: {len(answered)} | ✅ Закрыто: {closed_count}\n"
    buttons = []
    if unanswered:
        msg += "\n*❗ Без ответа:*\n" + "".join(f"  #{t[0]} {t[1]}\n" for t in unanswered[:10])
        for tid, name, _ in unanswered[:10]:
            buttons.append([InlineKeyboardButton(text=f"❗ #{tid} {name}", callback_data=f"enter_chat_{tid}")])
    if answered:
        msg += "\n*📋 С ответом:*\n" + "".join(f"  #{t[0]} {t[1]}\n" for t in answered[:5])

    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")])
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


# ── Обращения мероприятия (для кнопки в мероприятии у модератора) ─────────────
@router.callback_query(F.data.startswith("event_support_admin_"))
async def event_support_admin(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔ Нет прав", show_alert=True)
    event_id = int(callback.data.split("_")[3])

    with Session() as session:
        # Тикеты связанные с этим мероприятием
        tickets = session.query(SupportTicket).filter(
            SupportTicket.status == 'open',
            SupportTicket.event_id == event_id
        ).order_by(SupportTicket.created_at.desc()).all()

        buttons = []
        for t in tickets:
            student = session.query(Student).filter_by(telegram_id=t.student_telegram_id).first()
            name = student.full_name if student else f"ID:{t.student_telegram_id}"
            has_reply = session.query(SupportMessage).filter(
                SupportMessage.ticket_id == t.id,
                SupportMessage.sender_id != t.student_telegram_id
            ).first() is not None
            icon = "📋" if has_reply else "❗"
            buttons.append([InlineKeyboardButton(text=f"{icon} #{t.id} {name}", callback_data=f"enter_chat_{t.id}")])

    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"event_{event_id}")])
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(
        f"🆘 Обращения мероприятия ({len(tickets)}):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
