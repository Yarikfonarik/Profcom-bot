# handlers/reg_requests.py — Заявки на регистрацию (admin + переписка)
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from database import Session
from models import Student, RegistrationRequest, RegRequestMessage
from config import ADMIN_IDS
from security import safe_int, rate_limited, validate_length, sanitize_text
from states import RegRequestReplyState

router = Router()

# Активные чаты по заявкам: {user_id: req_id}
_active_reg_chat: dict[int, int] = {}


# ─────────────────────────────────────────────────────────────────────────────
#  СПИСОК ЗАЯВОК (admin)
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "reg_requests_admin")
async def reg_requests_list(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав", show_alert=True)

    with Session() as session:
        pending = session.query(RegistrationRequest).filter_by(status='pending').order_by(
            RegistrationRequest.created_at.desc()).all()
        approved_count = session.query(RegistrationRequest).filter_by(status='approved').count()
        rejected_count = session.query(RegistrationRequest).filter_by(status='rejected').count()

    msg = (
        f"📋 *Заявки на регистрацию*\n\n"
        f"⏳ Ожидают: {len(pending)} | ✅ Одобрено: {approved_count} | ❌ Отклонено: {rejected_count}\n"
    )

    buttons = []
    for req in pending[:15]:
        buttons.append([InlineKeyboardButton(
            text=f"⏳ #{req.id} {req.full_name}",
            callback_data=f"view_reg_req_{req.id}"
        )])

    if not pending:
        msg += "\nНовых заявок нет."

    buttons.append([InlineKeyboardButton(text="📋 Показать все", callback_data="reg_requests_all")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад",       callback_data="admin_panel")])

    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(msg, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data == "reg_requests_all")
async def reg_requests_all(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав", show_alert=True)

    with Session() as session:
        all_reqs = session.query(RegistrationRequest).order_by(
            RegistrationRequest.created_at.desc()).limit(30).all()

    buttons = []
    for req in all_reqs:
        icons = {"pending": "⏳", "approved": "✅", "rejected": "❌"}
        icon = icons.get(req.status, "⏳")
        buttons.append([InlineKeyboardButton(
            text=f"{icon} #{req.id} {req.full_name}",
            callback_data=f"view_reg_req_{req.id}"
        )])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="reg_requests_admin")])

    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer("📋 Все заявки (последние 30):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


# ─────────────────────────────────────────────────────────────────────────────
#  ПРОСМОТР ЗАЯВКИ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("view_reg_req_"))
async def view_reg_request(callback: CallbackQuery):
    req_id = safe_int(callback.data.split("_")[3] if len(callback.data.split("_")) > 3 else "0")
    is_admin = callback.from_user.id in ADMIN_IDS

    with Session() as session:
        req = session.query(RegistrationRequest).get(req_id)
        if not req: return await callback.answer("Заявка не найдена")
        messages = session.query(RegRequestMessage).filter_by(request_id=req_id).order_by(
            RegRequestMessage.sent_at).all()

        history = []
        for m in messages:
            role = "🛡 Модератор" if m.sender_id in ADMIN_IDS else "👤 Заявитель"
            content = m.text or f"[{m.file_type}]"
            ts = m.sent_at.strftime("%d.%m %H:%M")
            history.append(f"[{ts}] {role}: {content}")

    icons = {"pending": "⏳", "approved": "✅", "rejected": "❌"}
    status_text = {"pending": "Ожидает", "approved": "Одобрена", "rejected": "Отклонена"}

    msg = (
        f"📋 *Заявка #{req.id}*\n"
        f"Статус: {icons.get(req.status,'⏳')} {status_text.get(req.status,'')}\n\n"
        f"👤 {req.full_name}\n"
        f"📅 Дата рождения: {req.birth_date or '—'}\n"
        f"🏛 Факультет: {req.faculty}\n"
        f"📱 Телефон: {req.phone or '—'}\n"
        f"🆔 TG ID: {req.telegram_id}\n"
    )
    if history:
        msg += "\n*Переписка:*\n" + "\n".join(history[-10:])

    buttons = []
    if is_admin:
        buttons.append([InlineKeyboardButton(text="💬 Написать заявителю", callback_data=f"reply_reg_{req_id}")])
        if req.status == 'pending':
            buttons.append([
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_reg_{req_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_reg_{req_id}"),
            ])
        buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="reg_requests_admin")])
    else:
        buttons.append([InlineKeyboardButton(text="💬 Написать", callback_data=f"reg_chat_{req_id}")])

    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(msg, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


# ─────────────────────────────────────────────────────────────────────────────
#  ОДОБРЕНИЕ / ОТКЛОНЕНИЕ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("approve_reg_"))
async def approve_reg(callback: CallbackQuery, bot: Bot):
    req_id = safe_int(callback.data.split("_")[2] if len(callback.data.split("_")) > 2 else "0")
    with Session() as session:
        req = session.query(RegistrationRequest).get(req_id)
        req.status = 'approved'
        session.commit()
        tg_id = req.telegram_id
        name = req.full_name

    await callback.answer("✅ Заявка одобрена!")
    try:
        await bot.send_message(
            tg_id,
            f"✅ *Ваша заявка одобрена!*\n\n"
            f"Здравствуйте, {name}!\n\n"
            f"Мы внесли вас в базу. Ваш баркод будет сообщён отдельным сообщением. "
            f"После получения баркода вы сможете войти в приложение.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔢 Войти по баркоду", callback_data="auth_barcode")]
            ])
        )
    except Exception: pass

    callback.data = f"view_reg_req_{req_id}"
    await view_reg_request(callback)


@router.callback_query(F.data.startswith("reject_reg_"))
async def reject_reg(callback: CallbackQuery, bot: Bot):
    req_id = safe_int(callback.data.split("_")[2] if len(callback.data.split("_")) > 2 else "0")
    with Session() as session:
        req = session.query(RegistrationRequest).get(req_id)
        req.status = 'rejected'
        session.commit()
        tg_id = req.telegram_id
        name = req.full_name

    await callback.answer("❌ Заявка отклонена")
    try:
        await bot.send_message(
            tg_id,
            f"😔 *Ваша заявка отклонена.*\n\n"
            f"Здравствуйте, {name}!\n\n"
            f"К сожалению, мы не смогли подтвердить ваши данные. "
            f"Если считаете это ошибкой — обратитесь в Профком: 📍 И-108",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🆘 Поддержка", callback_data="support_unreg")]
            ])
        )
    except Exception: pass

    callback.data = f"view_reg_req_{req_id}"
    await view_reg_request(callback)


# ─────────────────────────────────────────────────────────────────────────────
#  ПЕРЕПИСКА ПО ЗАЯВКЕ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("reply_reg_"))
async def reply_reg_start(callback: CallbackQuery, state: FSMContext):
    req_id = safe_int(callback.data.split("_")[2] if len(callback.data.split("_")) > 2 else "0")
    _active_reg_chat[callback.from_user.id] = req_id
    await callback.message.answer(
        "✏️ Напишите сообщение заявителю:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"view_reg_req_{req_id}")]
        ])
    )
    await state.update_data(reg_reply_req_id=req_id)
    await state.set_state(RegRequestReplyState.AWAITING_MESSAGE)


@router.message(RegRequestReplyState.AWAITING_MESSAGE)
async def send_reg_reply(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    req_id = data.get("reg_reply_req_id") or _active_reg_chat.get(message.from_user.id)
    await state.clear()
    _active_reg_chat.pop(message.from_user.id, None)

    if not req_id:
        return await message.answer("❌ Ошибка: заявка не найдена.")

    sender_id = message.from_user.id
    file_id, file_type = None, None
    if message.photo:      file_id = message.photo[-1].file_id; file_type = 'photo'
    elif message.document: file_id = message.document.file_id;  file_type = 'document'
    elif message.voice:    file_id = message.voice.file_id;     file_type = 'voice'

    with Session() as session:
        req = session.query(RegistrationRequest).get(req_id)
        if not req: return await message.answer("❌ Заявка не найдена.")
        session.add(RegRequestMessage(
            request_id=req_id, sender_id=sender_id,
            text=message.text or message.caption, file_id=file_id, file_type=file_type
        ))
        session.commit()
        target_id = req.telegram_id if sender_id in ADMIN_IDS else None

        # Находим модераторов для уведомления если студент пишет
        if sender_id not in ADMIN_IDS:
            from handlers.support import _get_mods
            mods = _get_mods(session)
            mod_ids = [m[0] for m in mods]
        else:
            mod_ids = []

    is_admin_sender = sender_id in ADMIN_IDS
    sender_name = message.from_user.full_name or "Пользователь"
    header = f"{'🛡 Модератор' if is_admin_sender else '👤 Заявитель'} ({sender_name}):\n\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Открыть заявку", callback_data=f"view_reg_req_{req_id}")]
    ])

    # Отправляем заявителю (если пишет модератор)
    if is_admin_sender and target_id:
        try:
            if message.text:
                await bot.send_message(target_id, f"📩 *Ответ по заявке #{req_id}:*\n\n{message.text}",
                    parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="💬 Ответить", callback_data=f"reg_chat_{req_id}")]
                    ]))
            elif message.photo:
                await bot.send_photo(target_id, message.photo[-1].file_id,
                    caption=f"📩 Ответ по заявке #{req_id}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="💬 Ответить", callback_data=f"reg_chat_{req_id}")]
                    ]))
        except Exception: pass

    # Уведомляем модераторов (если пишет заявитель)
    if not is_admin_sender:
        for mod_id in mod_ids:
            try:
                content = message.text or "[медиа]"
                await bot.send_message(mod_id,
                    f"📋 *Новое сообщение по заявке #{req_id}*\n\n{header}{content}",
                    parse_mode="Markdown", reply_markup=kb)
            except Exception: pass

    await message.answer("✅ Сообщение отправлено!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 К заявке", callback_data=f"view_reg_req_{req_id}")]
    ]))


# ─────────────────────────────────────────────────────────────────────────────
#  СТУДЕНТ ОТКРЫВАЕТ ЧАТ ПО ЗАЯВКЕ (из уведомления)
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("reg_chat_"))
async def reg_chat_student(callback: CallbackQuery, state: FSMContext):
    req_id = safe_int(callback.data.split("_")[2] if len(callback.data.split("_")) > 2 else "0")
    _active_reg_chat[callback.from_user.id] = req_id
    await state.update_data(reg_reply_req_id=req_id)
    await state.set_state(RegRequestReplyState.AWAITING_MESSAGE)
    await callback.message.answer(
        f"💬 *Переписка по заявке #{req_id}*\n\nНапишите ваш вопрос или дополнение:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_start")]
        ])
    )
