# handlers/support.py
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from database import Session
from models import Student, SupportTicket, SupportMessage
from config import ADMIN_IDS
from states import SupportState

router = Router()


def _get_mods(session) -> list[tuple[int, str]]:
    """Возвращает список (telegram_id, имя) модераторов."""
    mods = session.query(Student).filter(
        Student.role.in_(["admin", "moderator"]),
        Student.telegram_id != None
    ).all()
    result = [(m.telegram_id, m.full_name) for m in mods]
    for a in ADMIN_IDS:
        if not any(r[0] == a for r in result):
            result.append((a, f"Администратор ({a})"))
    return result


def _student_reply_kb(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Ответить", callback_data=f"student_reply_{ticket_id}")]
    ])


def _mod_kb(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Ответить",               callback_data=f"reply_ticket_{ticket_id}")],
        [InlineKeyboardButton(text="🔄 Передать модератору",    callback_data=f"transfer_choose_{ticket_id}")],
        [InlineKeyboardButton(text="✅ Закрыть тикет",          callback_data=f"close_ticket_{ticket_id}")],
    ])


async def support_start_msg(message: Message, state: FSMContext):
    """Запуск поддержки из команды /help."""
    await state.clear()
    user_id = message.from_user.id
    with Session() as session:
        ticket = session.query(SupportTicket).filter_by(student_telegram_id=user_id, status='open').first()
        ticket_id = ticket.id if ticket else None
    if ticket_id:
        await state.update_data(ticket_id=ticket_id)
    await state.set_state(SupportState.AWAITING_MESSAGE)
    await message.answer(
        "🆘 *Поддержка*\n\nНапиши сообщение — текст, фото, документ, голосовое или видео.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_back")]
        ])
    )


@router.callback_query(F.data == "support")
async def support_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    with Session() as session:
        ticket = session.query(SupportTicket).filter_by(student_telegram_id=user_id, status='open').first()
        ticket_id = ticket.id if ticket else None
    if ticket_id:
        await state.update_data(ticket_id=ticket_id)
    await state.set_state(SupportState.AWAITING_MESSAGE)
    await callback.message.answer(
        "🆘 *Поддержка*\n\nНапиши сообщение — текст, фото, документ, голосовое или видео.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_back")]
        ])
    )


@router.callback_query(F.data == "support_unreg")
async def support_unreg(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(SupportState.AWAITING_MESSAGE)
    await callback.message.answer(
        "🆘 *Поддержка*\n\nНапиши сообщение.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_support")]
        ])
    )


@router.callback_query(F.data == "cancel_support")
async def cancel_support(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Отменено.")


@router.message(SupportState.AWAITING_MESSAGE)
async def receive_support_message(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    data = await state.get_data()
    await state.clear()

    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()

        ticket = None
        if data.get("ticket_id"):
            ticket = session.query(SupportTicket).get(data["ticket_id"])
        if not ticket:
            ticket = session.query(SupportTicket).filter_by(student_telegram_id=user_id, status='open').first()
        if not ticket:
            ticket = SupportTicket(student_telegram_id=user_id)
            session.add(ticket)
            session.flush()

        file_id, file_type = None, None
        if message.photo:     file_id = message.photo[-1].file_id; file_type = 'photo'
        elif message.document: file_id = message.document.file_id; file_type = 'document'
        elif message.voice:    file_id = message.voice.file_id;    file_type = 'voice'
        elif message.video:    file_id = message.video.file_id;    file_type = 'video'

        session.add(SupportMessage(
            ticket_id=ticket.id, sender_id=user_id,
            text=message.text or message.caption, file_id=file_id, file_type=file_type
        ))
        session.commit()

        ticket_id = ticket.id
        mod_id = ticket.moderator_telegram_id
        mods = _get_mods(session)

        if student:
            sender_info = f"👤 {student.full_name} | {student.barcode} | ID: {user_id}"
        else:
            sender_info = f"👤 {message.from_user.full_name or 'Неизв.'} | ID: {user_id}"

    header = f"📨 *Обращение #{ticket_id}*\n{sender_info}\n\n"
    targets = [mod_id] if mod_id else [m[0] for m in mods]
    kb = _mod_kb(ticket_id)

    for target in targets:
        try:
            if message.text:
                await bot.send_message(target, header + message.text, parse_mode="Markdown", reply_markup=kb)
            elif message.photo:
                await bot.send_photo(target, message.photo[-1].file_id,
                    caption=header + (message.caption or ""), parse_mode="Markdown", reply_markup=kb)
            elif message.document:
                await bot.send_document(target, message.document.file_id,
                    caption=header + (message.caption or ""), parse_mode="Markdown", reply_markup=kb)
            elif message.voice:
                await bot.send_voice(target, message.voice.file_id, caption=header, parse_mode="Markdown", reply_markup=kb)
            elif message.video:
                await bot.send_video(target, message.video.file_id,
                    caption=header + (message.caption or ""), parse_mode="Markdown", reply_markup=kb)
        except Exception:
            pass

    await message.answer(
        "✅ Сообщение отправлено! Ожидай ответа.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_back")]
        ])
    )


# ── Ответ модератора ─────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("reply_ticket_"))
async def reply_to_ticket(callback: CallbackQuery, state: FSMContext):
    ticket_id = int(callback.data.split("_")[2])
    await state.update_data(reply_ticket_id=ticket_id, reply_mod_id=callback.from_user.id)
    await state.set_state(SupportState.AWAITING_REPLY)
    await callback.message.answer(
        f"✏️ Ответ на тикет #{ticket_id}:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_reply")]
        ])
    )


@router.callback_query(F.data == "cancel_reply")
async def cancel_reply(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Отменено.")


@router.message(SupportState.AWAITING_REPLY)
async def send_mod_reply(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    ticket_id = data.get("reply_ticket_id")
    mod_id = data.get("reply_mod_id")
    await state.clear()

    with Session() as session:
        ticket = session.query(SupportTicket).get(ticket_id)
        if not ticket: return await message.answer("❌ Тикет не найден.")
        if not ticket.moderator_telegram_id:
            ticket.moderator_telegram_id = mod_id

        file_id, file_type = None, None
        if message.photo:     file_id = message.photo[-1].file_id; file_type = 'photo'
        elif message.document: file_id = message.document.file_id; file_type = 'document'
        elif message.voice:    file_id = message.voice.file_id;    file_type = 'voice'
        elif message.video:    file_id = message.video.file_id;    file_type = 'video'

        session.add(SupportMessage(ticket_id=ticket_id, sender_id=mod_id,
            text=message.text or message.caption, file_id=file_id, file_type=file_type))
        session.commit()
        student_tg = ticket.student_telegram_id

    mod_name = message.from_user.full_name or "Модератор"
    header = f"📩 *Ответ от модератора ({mod_name}):*\n\n"
    kb = _student_reply_kb(ticket_id)

    try:
        if message.text:
            await bot.send_message(student_tg, header + message.text, parse_mode="Markdown", reply_markup=kb)
        elif message.photo:
            await bot.send_photo(student_tg, message.photo[-1].file_id,
                caption=header + (message.caption or ""), parse_mode="Markdown", reply_markup=kb)
        elif message.document:
            await bot.send_document(student_tg, message.document.file_id,
                caption=header + (message.caption or ""), parse_mode="Markdown", reply_markup=kb)
        elif message.voice:
            await bot.send_voice(student_tg, message.voice.file_id, caption=header, parse_mode="Markdown", reply_markup=kb)
        elif message.video:
            await bot.send_video(student_tg, message.video.file_id,
                caption=header + (message.caption or ""), parse_mode="Markdown", reply_markup=kb)
        await message.answer("✅ Ответ отправлен!")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


# ── Студент отвечает ──────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("student_reply_"))
async def student_reply_start(callback: CallbackQuery, state: FSMContext):
    ticket_id = int(callback.data.split("_")[2])
    await state.update_data(ticket_id=ticket_id)
    await state.set_state(SupportState.AWAITING_MESSAGE)
    await callback.message.answer("✏️ Введи ответ модератору:")


# ── Передать тикет — выбор модератора ────────────────────────────────────────
@router.callback_query(F.data.startswith("transfer_choose_"))
async def transfer_choose(callback: CallbackQuery):
    ticket_id = int(callback.data.split("_")[2])
    sender_id = callback.from_user.id

    with Session() as session:
        mods = _get_mods(session)

    # Кнопки с именами модераторов (кроме текущего)
    buttons = []
    for mod_tg_id, mod_name in mods:
        if mod_tg_id != sender_id:
            buttons.append([InlineKeyboardButton(
                text=f"👤 {mod_name}",
                callback_data=f"do_transfer_{ticket_id}_{mod_tg_id}"
            )])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_reply")])

    if not buttons[:-1]:
        return await callback.answer("Нет других модераторов", show_alert=True)

    await callback.message.answer(
        "Выберите модератора для передачи тикета:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data.startswith("do_transfer_"))
async def do_transfer_ticket(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split("_")
    ticket_id = int(parts[2])
    new_mod_id = int(parts[3])
    sender_id = callback.from_user.id

    with Session() as session:
        ticket = session.query(SupportTicket).get(ticket_id)
        if not ticket: return await callback.answer("Тикет не найден")

        messages = session.query(SupportMessage).filter_by(ticket_id=ticket_id).order_by(SupportMessage.sent_at).all()
        history_lines = []
        for sm in messages:
            role = "Студент" if sm.sender_id == ticket.student_telegram_id else "Модератор"
            ts = sm.sent_at.strftime("%H:%M")
            text = sm.text or f"[{sm.file_type}]"
            history_lines.append(f"[{ts}] {role}: {text}")

        ticket.moderator_telegram_id = new_mod_id
        session.commit()
        student_tg = ticket.student_telegram_id

    history_text = "\n".join(history_lines) if history_lines else "(история пуста)"
    kb = _mod_kb(ticket_id)
    header = (
        f"🔄 *Тикет #{ticket_id} передан вам*\n\n"
        f"*История:*\n{history_text}\n\n"
        f"Ответьте студенту:"
    )
    try:
        await bot.send_message(new_mod_id, header, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        pass

    await callback.answer("✅ Тикет передан", show_alert=True)
    try: await callback.message.delete()
    except Exception: pass


# ── Закрыть тикет ────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("close_ticket_"))
async def close_ticket(callback: CallbackQuery):
    ticket_id = int(callback.data.split("_")[2])
    with Session() as session:
        ticket = session.query(SupportTicket).get(ticket_id)
        if ticket:
            ticket.status = 'closed'
            session.commit()
    await callback.answer("✅ Тикет закрыт")
    try: await callback.message.delete()
    except Exception: pass


# ── Панель обращений (модератор) ──────────────────────────────────────────────
@router.callback_query(F.data == "support_admin")
async def support_admin(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав", show_alert=True)

    with Session() as session:
        open_tickets = session.query(SupportTicket).filter_by(status='open').order_by(SupportTicket.created_at.desc()).all()
        closed_count = session.query(SupportTicket).filter_by(status='closed').count()

        unanswered = []
        assigned = []
        for t in open_tickets:
            # Проверяем есть ли ответ модератора
            has_mod_reply = session.query(SupportMessage).filter(
                SupportMessage.ticket_id == t.id,
                SupportMessage.sender_id != t.student_telegram_id
            ).first() is not None

            student = session.query(Student).filter_by(telegram_id=t.student_telegram_id).first()
            student_name = student.full_name if student else f"ID: {t.student_telegram_id}"
            mod_name = None
            if t.moderator_telegram_id:
                mod = session.query(Student).filter_by(telegram_id=t.moderator_telegram_id).first()
                mod_name = mod.full_name if mod else f"ID: {t.moderator_telegram_id}"

            info = (t.id, student_name, mod_name, has_mod_reply)
            if has_mod_reply:
                assigned.append(info)
            else:
                unanswered.append(info)

    msg = f"🆘 *Обращения в поддержку*\n\n"
    msg += f"🔴 Без ответа: {len(unanswered)}\n"
    msg += f"🟢 С ответом: {len(assigned)}\n"
    msg += f"✅ Закрыто: {closed_count}\n\n"

    buttons = []
    if unanswered:
        msg += "❗ *Без ответа:*\n"
        for tid, sname, mname, _ in unanswered[:10]:
            msg += f"  #{tid} — {sname}\n"
            buttons.append([InlineKeyboardButton(
                text=f"❗ #{tid} {sname}",
                callback_data=f"view_ticket_{tid}"
            )])

    if assigned:
        msg += "\n📋 *С ответом:*\n"
        for tid, sname, mname, _ in assigned[:5]:
            mod_info = f" → {mname}" if mname else ""
            msg += f"  #{tid} — {sname}{mod_info}\n"

    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")])
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("view_ticket_"))
async def view_ticket(callback: CallbackQuery):
    ticket_id = int(callback.data.split("_")[2])
    with Session() as session:
        ticket = session.query(SupportTicket).get(ticket_id)
        if not ticket: return await callback.answer("Тикет не найден")
        messages = session.query(SupportMessage).filter_by(ticket_id=ticket_id).order_by(SupportMessage.sent_at).all()
        student = session.query(Student).filter_by(telegram_id=ticket.student_telegram_id).first()
        student_name = student.full_name if student else f"ID: {ticket.student_telegram_id}"
        history = []
        for sm in messages:
            role = "👤 Студент" if sm.sender_id == ticket.student_telegram_id else "🛡 Модератор"
            ts = sm.sent_at.strftime("%d.%m %H:%M")
            text = sm.text or f"[{sm.file_type}]"
            history.append(f"[{ts}] {role}: {text}")

    msg = f"📋 *Тикет #{ticket_id}*\n👤 {student_name}\n\n"
    msg += "\n".join(history) if history else "(нет сообщений)"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Ответить",            callback_data=f"reply_ticket_{ticket_id}")],
        [InlineKeyboardButton(text="🔄 Передать",            callback_data=f"transfer_choose_{ticket_id}")],
        [InlineKeyboardButton(text="✅ Закрыть",             callback_data=f"close_ticket_{ticket_id}")],
        [InlineKeyboardButton(text="⬅️ Назад",              callback_data="support_admin")],
    ])
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=kb)
