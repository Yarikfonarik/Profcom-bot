# handlers/registration.py
import os, re, hashlib
import aiohttp

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from models import Student, RegistrationRequest
from states import (StudentVerificationState, PhoneAuthState, RegistrationRequestState)
from database import Session
from config import ADMIN_IDS
from keyboards import main_menu_keyboard, REMOVE_KEYBOARD
from security import (
    otp_create, otp_verify, otp_refresh, otp_can_resend, otp_get_meta,
    rate_limited, validate_length, sanitize_text
)

router = Router()

NOTISEND_PROJECT = os.environ.get("NOTISEND_PROJECT", "")
NOTISEND_API_KEY  = os.environ.get("NOTISEND_API_KEY", "")
NOTISEND_SENDER   = os.environ.get("NOTISEND_SENDER", "Profkom")


def _normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", str(raw))
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]
    if len(digits) == 10:
        digits = "7" + digits
    return "+" + digits


def _is_valid_phone(phone: str) -> bool:
    return bool(re.match(r"^\+7\d{10}$", phone))


def _make_sign(params: dict, api_key: str) -> str:
    sorted_values = [str(v) for _, v in sorted(params.items())]
    step1 = ";".join(sorted_values) + ";" + api_key
    step2 = hashlib.sha1(step1.encode()).hexdigest()
    return hashlib.md5(step2.encode()).hexdigest()


async def _send_otp(phone: str, code: str) -> dict:
    message_text = f"Ваш код подтверждения Профком ЧГУ: {code}"
    params = {
        "message":    message_text,
        "project":    NOTISEND_PROJECT,
        "recipients": phone.lstrip("+"),
        "sender":     NOTISEND_SENDER,
    }
    params["sign"] = _make_sign(params, NOTISEND_API_KEY)
    url = "https://sms.notisend.ru/api/message/send"
    async with aiohttp.ClientSession() as s:
        async with s.post(url, data=params) as resp:
            try: return await resp.json(content_type=None)
            except Exception: return {"status": "error", "message": await resp.text()}


def _send_ok(result) -> bool:
    if isinstance(result, list): return True
    if isinstance(result, dict): return result.get("status") == "success"
    return False


def _start_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Войти по номеру телефона",   callback_data="auth_phone")],
        [InlineKeyboardButton(text="🔢 Войти по баркоду",           callback_data="auth_barcode")],
        [InlineKeyboardButton(text="📝 Подать заявку на вступление", callback_data="request_registration")],
        [InlineKeyboardButton(text="🆘 Поддержка",                  callback_data="support_unreg")],
    ])


# ─────────────────────────────────────────────────────────────────────────────
#  /start
# ─────────────────────────────────────────────────────────────────────────────

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    await message.answer("👋", reply_markup=REMOVE_KEYBOARD)

    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()

    if student:
        return await message.answer("🏠 Главное меню:",
            reply_markup=main_menu_keyboard(user_id in ADMIN_IDS))

    await message.answer("🚀 *Добро пожаловать в Профком ЧГУ!*\n\nВыберите действие:",
        parse_mode="Markdown", reply_markup=_start_kb())


# ─────────────────────────────────────────────────────────────────────────────
#  ВХОД ПО ТЕЛЕФОНУ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "auth_phone")
async def auth_phone_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(PhoneAuthState.AWAITING_PHONE)
    await callback.message.answer(
        "📱 Введите ваш номер телефона:\n\nПример: +79001234567 или 89001234567",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_start")]
        ])
    )


@router.message(PhoneAuthState.AWAITING_PHONE)
async def auth_phone_receive(message: Message, state: FSMContext):
    raw = message.text.strip() if message.text else ""
    phone = _normalize_phone(raw)
    if not _is_valid_phone(phone):
        return await message.answer("❗ Неверный формат. Пример: +79001234567 или 89001234567")

    with Session() as session:
        student = session.query(Student).filter_by(phone=phone).first()

    if not student:
        await state.clear()
        return await message.answer(
            f"❌ Номер {phone} не найден в базе.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📝 Подать заявку",      callback_data="request_registration")],
                [InlineKeyboardButton(text="🔢 Войти по баркоду",   callback_data="auth_barcode")],
                [InlineKeyboardButton(text="⬅️ Назад",              callback_data="back_to_start")],
            ])
        )

    user_id = message.from_user.id
    # Уже привязан к этому же аккаунту
    if student.telegram_id == user_id:
        await state.clear()
        return await message.answer("✅ Ты уже авторизован!",
            reply_markup=main_menu_keyboard(user_id in ADMIN_IDS))

    # Привязан к другому — блокируем
    if student.telegram_id and student.telegram_id != user_id:
        await state.clear()
        return await message.answer(
            "⚠️ Этот номер уже привязан к другому аккаунту.\nОбратитесь в поддержку для отвязки.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🆘 Поддержка", callback_data="support_unreg")]
            ])
        )

    code = otp_create(user_id, phone, student.id)
    await message.answer("⏳ Отправляем код в Telegram...")
    result = await _send_otp(phone, code)

    if not _send_ok(result):
        err = result.get("message", str(result)) if isinstance(result, dict) else str(result)
        return await message.answer(
            f"❌ Не удалось отправить код: {err}\n\nВойдите по баркоду:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔢 Войти по баркоду", callback_data="auth_barcode")]
            ])
        )

    await state.update_data(phone=phone, student_id=student.id)
    await state.set_state(PhoneAuthState.AWAITING_CODE)
    await message.answer(
        f"✅ Код отправлен на номер {phone}!\n\nВведите 6-значный код:\n_(код действует 5 минут)_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Отправить снова", callback_data="resend_code")],
            [InlineKeyboardButton(text="⬅️ Назад",           callback_data="back_to_start")],
        ])
    )


@router.callback_query(F.data == "resend_code")
async def resend_code(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    can, remaining = otp_can_resend(uid)
    if not can:
        return await callback.answer(
            f"⏳ Повторная отправка через {remaining} сек.", show_alert=True
        )
    data = await state.get_data()
    phone = data.get("phone")
    if not phone:
        return await callback.answer("Начните заново", show_alert=True)
    new_code = otp_refresh(uid)
    if not new_code:
        return await callback.answer("Сессия устарела. Начните заново.", show_alert=True)
    await callback.answer("⏳")
    await _send_otp(phone, new_code)
    await callback.message.answer("✅ Новый код отправлен! _(действует 5 минут)_", parse_mode="Markdown")


@router.message(PhoneAuthState.AWAITING_CODE)
async def auth_code_receive(message: Message, state: FSMContext):
    code_input = (message.text or "").strip()
    if not re.match(r"^\d{6}$", code_input):
        return await message.answer("❗ Введите 6-значный код:")

    user_id = message.from_user.id
    ok, err_msg = otp_verify(user_id, code_input)

    if not ok:
        if "устарела" in err_msg or "истёк" in err_msg or "попытк" in err_msg:
            await state.clear()
            return await message.answer(
                f"❌ {err_msg}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Начать заново", callback_data="auth_phone")]
                ])
            )
        return await message.answer(err_msg)

    meta = otp_get_meta(user_id) or (await state.get_data())
    student_id = meta.get("student_id")

    with Session() as session:
        student = session.query(Student).get(student_id)
        if not student:
            await state.clear()
            return await message.answer("❌ Ошибка. Студент не найден.")
        student.telegram_id = user_id
        session.commit()

    await state.clear()
    await message.answer("✅ Авторизация прошла успешно!")
    await message.answer("🏠 Главное меню:", reply_markup=main_menu_keyboard(user_id in ADMIN_IDS))


# ─────────────────────────────────────────────────────────────────────────────
#  ВХОД ПО БАРКОДУ — telegram_id привязывается навсегда, отвязать может только админ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "auth_barcode")
async def auth_barcode_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(StudentVerificationState.AWAITING_BARCODE)
    await callback.message.answer(
        "🔢 Введите ваш баркод (13 цифр):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_start")]
        ])
    )


@router.callback_query(F.data == "begin_register")
async def handle_start_old(callback: CallbackQuery, state: FSMContext):
    callback.data = "auth_barcode"
    await auth_barcode_start(callback, state)


@router.message(StudentVerificationState.AWAITING_BARCODE)
async def register_by_barcode(message: Message, state: FSMContext):
    barcode = message.text.strip() if message.text else ""
    if not barcode.isdigit() or len(barcode) != 13:
        return await message.answer("❗ Баркод — 13 цифр")

    user_id = message.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(barcode=barcode).first()
        if not student:
            return await message.answer(
                "❌ Баркод не найден. Обратись в Профком: 📍 И-108",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🆘 Поддержка",         callback_data="support_unreg")],
                    [InlineKeyboardButton(text="📱 Войти по телефону", callback_data="auth_phone")],
                ])
            )

        # Уже этот же пользователь
        if student.telegram_id == user_id:
            await state.clear()
            return await message.answer("✅ Ты уже авторизован!",
                reply_markup=main_menu_keyboard(user_id in ADMIN_IDS))

        # Привязан к другому — запрещаем
        if student.telegram_id and student.telegram_id != user_id:
            return await message.answer(
                "⚠️ Этот баркод уже привязан к другому аккаунту.\n\n"
                "Если ты сменил аккаунт — обратись к администратору для отвязки.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🆘 Поддержка", callback_data="support_unreg")]
                ])
            )

        # Свободный баркод — привязываем
        student.telegram_id = user_id
        session.commit()

    await state.clear()
    await message.answer("✅ Готово!")
    await message.answer("🏠 Главное меню:", reply_markup=main_menu_keyboard(user_id in ADMIN_IDS))


# ─────────────────────────────────────────────────────────────────────────────
#  ЗАЯВКА НА ВСТУПЛЕНИЕ — только сбор данных для модерации
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "request_registration")
async def start_reg_request(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(RegistrationRequestState.AWAITING_FIO)
    await callback.message.answer(
        "📝 *Заявка на вступление в Профком ЧГУ*\n\n"
        "Напишите нам ваше:\n\n"
        "*1. ФИО* (полностью, например: Иванов Иван Иванович):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_start")]
        ])
    )


@router.message(RegistrationRequestState.AWAITING_FIO)
async def reg_fio(message: Message, state: FSMContext):
    text = sanitize_text(message.text or "")
    ok, err = validate_length(text, "full_name")
    if not ok:
        return await message.answer(err)
    await state.update_data(full_name=text)
    await message.answer("*2. Дата рождения* (например: 01.01.2000):", parse_mode="Markdown")
    await state.set_state(RegistrationRequestState.AWAITING_BIRTH_DATE)


@router.message(RegistrationRequestState.AWAITING_BIRTH_DATE)
async def reg_birth(message: Message, state: FSMContext):
    await state.update_data(birth_date=message.text.strip())
    await message.answer("*3. Факультет / Институт:*", parse_mode="Markdown")
    await state.set_state(RegistrationRequestState.AWAITING_FACULTY)


@router.message(RegistrationRequestState.AWAITING_FACULTY)
async def reg_faculty(message: Message, state: FSMContext):
    text = sanitize_text(message.text or "")
    ok, err = validate_length(text, "faculty")
    if not ok:
        return await message.answer(err)
    await state.update_data(faculty=text)
    await message.answer("*4. Номер телефона* (или «нет»):", parse_mode="Markdown")
    await state.set_state(RegistrationRequestState.AWAITING_PHONE)


@router.message(RegistrationRequestState.AWAITING_PHONE)
async def reg_phone(message: Message, state: FSMContext, bot: Bot):
    raw = message.text.strip() if message.text else "нет"
    phone = _normalize_phone(raw) if raw.lower() != "нет" else None
    data = await state.get_data()
    user_id = message.from_user.id

    with Session() as session:
        req = RegistrationRequest(
            telegram_id=user_id,
            full_name=data["full_name"],
            birth_date=data.get("birth_date"),
            faculty=data["faculty"],
            phone=phone,
            status='pending'
        )
        session.add(req)
        session.commit()
        req_id = req.id

    await state.clear()
    await message.answer(
        "✅ *Заявка отправлена!*\n\n"
        "Мы внесём вас в базу и зарезервируем баркод — после чего свяжемся с вами здесь.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Написать вопрос", callback_data=f"reg_chat_{req_id}")]
        ])
    )

    # Уведомление модераторам
    from handlers.support import _get_mods
    with Session() as session:
        mods = _get_mods(session)

    notif = (
        f"📋 *Новая заявка #{req_id}*\n\n"
        f"👤 {data['full_name']}\n"
        f"📅 {data.get('birth_date','—')}\n"
        f"🏛 {data['faculty']}\n"
        f"📱 {phone or '—'}\n"
        f"🆔 TG: {user_id}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Открыть заявку", callback_data=f"view_reg_req_{req_id}")]
    ])
    for mod_id, _ in mods:
        try: await bot.send_message(mod_id, notif, parse_mode="Markdown", reply_markup=kb)
        except Exception: pass


@router.callback_query(F.data.startswith("reg_chat_"))
async def reg_chat_open(callback: CallbackQuery, state: FSMContext):
    req_id = safe_int(callback.data.split("_")[2] if len(callback.data.split("_")) > 2 else "0")
    await state.update_data(reg_reply_req_id=req_id)
    from states import RegRequestReplyState
    await state.set_state(RegRequestReplyState.AWAITING_MESSAGE)
    await callback.message.answer(
        "✏️ Напишите вопрос или дополнение к заявке:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_start")]
        ])
    )


@router.callback_query(F.data == "back_to_start")
async def back_to_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
    try: await callback.message.delete()
    except Exception: pass
    if student:
        return await callback.message.answer("🏠 Главное меню:",
            reply_markup=main_menu_keyboard(user_id in ADMIN_IDS))
    await callback.message.answer("🚀 *Добро пожаловать в Профком ЧГУ!*",
        parse_mode="Markdown", reply_markup=_start_kb())
