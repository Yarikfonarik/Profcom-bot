# handlers/support.py
# Студент может писать в поддержку, модератор отвечает → студент получает ответ с кнопкой «↩️ Ответить»
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from database import Session
from models import Student
from config import ADMIN_IDS
from states import SupportState

router = Router()


async def _get_support_targets(session) -> list[int]:
    moderators = session.query(Student).filter(
        Student.role.in_(["admin", "moderator"]),
        Student.telegram_id != None
    ).all()
    targets = [s.telegram_id for s in moderators]
    for admin_id in ADMIN_IDS:
        if admin_id not in targets:
            targets.append(admin_id)
    return targets


@router.callback_query(F.data == "support")
async def support_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(
        "🆘 *Поддержка*\n\n"
        "Напиши сообщение или прикрепи файл — передадим модератору.\n"
        "Можно отправить текст, фото, документ или голосовое.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="menu_back")]
        ])
    )
    await state.set_state(SupportState.AWAITING_MESSAGE)


@router.callback_query(F.data == "support_unreg")
async def support_unreg(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(
        "🆘 *Поддержка*\n\nНапиши сообщение или прикрепи файл.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_support")]
        ])
    )
    await state.set_state(SupportState.AWAITING_MESSAGE)


@router.callback_query(F.data == "cancel_support")
async def cancel_support(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Отменено.")


@router.message(SupportState.AWAITING_MESSAGE)
async def receive_support_message(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id

    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        targets = await _get_support_targets(session)

    if student:
        sender_info = f"👤 {student.full_name} | {student.barcode} | ID: {user_id}"
    else:
        name = message.from_user.full_name or "Неизвестный"
        username = f"@{message.from_user.username}" if message.from_user.username else ""
        sender_info = f"👤 {name} {username} | ID: {user_id} | (не зарег.)"

    header = f"📨 *Обращение в поддержку*\n{sender_info}\n\n"

    # Кнопка ответить — передаёт user_id для ответа
    reply_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Ответить", callback_data=f"reply_to_{user_id}")]
    ])

    for target in targets:
        try:
            if message.text:
                await bot.send_message(target, header + message.text, parse_mode="Markdown", reply_markup=reply_kb)
            elif message.photo:
                await bot.send_photo(target, message.photo[-1].file_id,
                    caption=header + (message.caption or ""), parse_mode="Markdown", reply_markup=reply_kb)
            elif message.document:
                await bot.send_document(target, message.document.file_id,
                    caption=header + (message.caption or ""), parse_mode="Markdown", reply_markup=reply_kb)
            elif message.voice:
                await bot.send_voice(target, message.voice.file_id,
                    caption=header, parse_mode="Markdown", reply_markup=reply_kb)
            elif message.video:
                await bot.send_video(target, message.video.file_id,
                    caption=header + (message.caption or ""), parse_mode="Markdown", reply_markup=reply_kb)
        except Exception:
            pass

    await state.clear()
    await message.answer(
        "✅ Сообщение отправлено! Ожидай ответа.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_back")]
        ])
    )


# ── Модератор нажимает «Ответить» ────────────────────────────────────────────
@router.callback_query(F.data.startswith("reply_to_"))
async def start_reply(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split("_")[2])
    await state.update_data(reply_to=user_id)
    await state.set_state(SupportState.AWAITING_REPLY)
    await callback.message.answer(
        "✏️ Введите ответ (текст, фото или файл):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_reply")]
        ])
    )


@router.callback_query(F.data == "cancel_reply")
async def cancel_reply(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Отменено.")


@router.message(SupportState.AWAITING_REPLY)
async def send_reply(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    target_id = data.get("reply_to")
    await state.clear()

    if not target_id:
        return await message.answer("❌ Ошибка — не найден получатель.")

    mod_name = message.from_user.full_name or "Модератор"
    header = f"📩 *Ответ от модератора ({mod_name}):*\n\n"

    # Студент может ответить обратно
    reply_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Ответить", callback_data="support")]
    ])

    try:
        if message.text:
            await bot.send_message(target_id, header + message.text, parse_mode="Markdown", reply_markup=reply_kb)
        elif message.photo:
            await bot.send_photo(target_id, message.photo[-1].file_id,
                caption=header + (message.caption or ""), parse_mode="Markdown", reply_markup=reply_kb)
        elif message.document:
            await bot.send_document(target_id, message.document.file_id,
                caption=header + (message.caption or ""), parse_mode="Markdown", reply_markup=reply_kb)
        elif message.voice:
            await bot.send_voice(target_id, message.voice.file_id,
                caption=header, parse_mode="Markdown", reply_markup=reply_kb)
        await message.answer("✅ Ответ отправлен!")
    except Exception as e:
        await message.answer(f"❌ Не удалось: {e}")
