# handlers/support.py
# Приватные тикеты: студент ↔ один модератор. Можно передать другому модератору.
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from database import Session
from models import Student, SupportTicket, SupportMessage
from config import ADMIN_IDS
from states import SupportState

router = Router()


def _get_mods(session) -> list[int]:
    mods = session.query(Student).filter(
        Student.role.in_(["admin", "moderator"]),
        Student.telegram_id != None
    ).all()
    ids = [m.telegram_id for m in mods]
    for a in ADMIN_IDS:
        if a not in ids:
            ids.append(a)
    return ids


def _ticket_kb(ticket_id: int, show_transfer: bool = False) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="↩️ Ответить", callback_data=f"reply_ticket_{ticket_id}")]]
    if show_transfer:
        rows.append([InlineKeyboardButton(text="🔄 Передать другому модератору", callback_data=f"transfer_ticket_{ticket_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _student_reply_kb(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Ответить", callback_data=f"student_reply_{ticket_id}")]
    ])


@router.callback_query(F.data == "support")
async def support_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id

    # Ищем открытый тикет
    with Session() as session:
        ticket = session.query(SupportTicket).filter_by(
            student_telegram_id=user_id, status='open'
        ).order_by(SupportTicket.created_at.desc()).first()
        ticket_id = ticket.id if ticket else None

    if ticket_id:
        await state.update_data(ticket_id=ticket_id)
    await state.set_state(SupportState.AWAITING_MESSAGE)

    await callback.message.answer(
        "🆘 *Поддержка*\n\nНапиши сообщение — текст, фото, документ или голосовое.",
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

        # Получаем или создаём тикет
        ticket = None
        if data.get("ticket_id"):
            ticket = session.query(SupportTicket).get(data["ticket_id"])
        if not ticket:
            ticket = session.query(SupportTicket).filter_by(
                student_telegram_id=user_id, status='open'
            ).order_by(SupportTicket.created_at.desc()).first()
        if not ticket:
            ticket = SupportTicket(student_telegram_id=user_id)
            session.add(ticket)
            session.flush()

        # Сохраняем сообщение
        file_id, file_type = None, None
        if message.photo:
            file_id = message.photo[-1].file_id
            file_type = 'photo'
        elif message.document:
            file_id = message.document.file_id
            file_type = 'document'
        elif message.voice:
            file_id = message.voice.file_id
            file_type = 'voice'
        elif message.video:
            file_id = message.video.file_id
            file_type = 'video'

        sm = SupportMessage(
            ticket_id=ticket.id,
            sender_id=user_id,
            text=message.text or message.caption,
            file_id=file_id,
            file_type=file_type
        )
        session.add(sm)
        session.commit()

        ticket_id = ticket.id
        mod_id = ticket.moderator_telegram_id

        if student:
            sender_info = f"👤 {student.full_name} | {student.barcode} | ID: {user_id}"
        else:
            name = message.from_user.full_name or "Неизв."
            sender_info = f"👤 {name} | ID: {user_id}"

        mods = _get_mods(session)

    header = f"📨 *Обращение #{ticket_id}*\n{sender_info}\n\n"

    # Если есть назначенный модератор — шлём только ему
    targets = [mod_id] if mod_id else mods

    for target in targets:
        try:
            kb = _ticket_kb(ticket_id, show_transfer=True)
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
        if not ticket:
            return await message.answer("❌ Тикет не найден.")

        # Назначаем модератора если не назначен
        if not ticket.moderator_telegram_id:
            ticket.moderator_telegram_id = mod_id

        file_id, file_type = None, None
        if message.photo:
            file_id = message.photo[-1].file_id; file_type = 'photo'
        elif message.document:
            file_id = message.document.file_id; file_type = 'document'
        elif message.voice:
            file_id = message.voice.file_id; file_type = 'voice'
        elif message.video:
            file_id = message.video.file_id; file_type = 'video'

        sm = SupportMessage(ticket_id=ticket_id, sender_id=mod_id,
            text=message.text or message.caption, file_id=file_id, file_type=file_type)
        session.add(sm)
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
        await message.answer(f"❌ Не удалось: {e}")


# ── Студент отвечает из уведомления ─────────────────────────────────────────
@router.callback_query(F.data.startswith("student_reply_"))
async def student_reply_start(callback: CallbackQuery, state: FSMContext):
    ticket_id = int(callback.data.split("_")[2])
    await state.update_data(ticket_id=ticket_id)
    await state.set_state(SupportState.AWAITING_MESSAGE)
    await callback.message.answer("✏️ Введи ответ модератору:")


# ── Передать тикет другому модератору ────────────────────────────────────────
@router.callback_query(F.data.startswith("transfer_ticket_"))
async def transfer_ticket(callback: CallbackQuery, bot: Bot):
    ticket_id = int(callback.data.split("_")[2])
    sender_id = callback.from_user.id

    with Session() as session:
        ticket = session.query(SupportTicket).get(ticket_id)
        if not ticket:
            return await callback.answer("Тикет не найден")

        # Все модераторы кроме текущего
        mods = _get_mods(session)
        other_mods = [m for m in mods if m != sender_id]

        if not other_mods:
            return await callback.answer("Нет других модераторов", show_alert=True)

        # Собираем историю сообщений
        messages = session.query(SupportMessage).filter_by(ticket_id=ticket_id).order_by(SupportMessage.sent_at).all()
        history_lines = []
        for sm in messages:
            role = "Студент" if sm.sender_id == ticket.student_telegram_id else "Модератор"
            ts = sm.sent_at.strftime("%H:%M")
            text = sm.text or f"[{sm.file_type}]"
            history_lines.append(f"[{ts}] {role}: {text}")

        history_text = "\n".join(history_lines) if history_lines else "(история пуста)"

        # Переназначаем
        old_mod = ticket.moderator_telegram_id
        new_mod = next(m for m in other_mods)
        ticket.moderator_telegram_id = new_mod
        session.commit()

        student_tg = ticket.student_telegram_id

    kb = _ticket_kb(ticket_id, show_transfer=True)
    header = (
        f"🔄 *Тикет #{ticket_id} передан вам*\n\n"
        f"*История переписки:*\n{history_text}\n\n"
        f"*Ответьте студенту:*"
    )
    try:
        await bot.send_message(new_mod, header, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        pass

    await callback.answer("✅ Тикет передан другому модератору", show_alert=True)
