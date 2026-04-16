# handlers/registration.py
import os
import re
import random
import hashlib
import aiohttp

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from models import Student, RegistrationRequest, RegRequestMessage
from states import (StudentVerificationState, PhoneAuthState, RegistrationRequestState)
from database import Session
from config import ADMIN_IDS
from keyboards import main_menu_keyboard, REMOVE_KEYBOARD

router = Router()

# Переменные окружения — добавь в BotHost
NOTISEND_PROJECT = os.environ.get("NOTISEND_PROJECT", "")
NOTISEND_API_KEY = os.environ.get("NOTISEND_API_KEY", "")
NOTISEND_SENDER  = os.environ.get("NOTISEND_SENDER", "ProfkomCHGU")

# Временное хранилище кодов: {user_id: {"code": "123456", "phone": "+7..."}}
_pending_codes: dict[int, dict] = {}


# ─────────────────────────────────────────────────────────────────────────────
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_phone(raw: str) -> str:
    """Приводит номер к формату +7XXXXXXXXXX."""
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]
    if len(digits) == 10:
        digits = "7" + digits
    return "+" + digits


def _is_valid_phone(phone: str) -> bool:
    return bool(re.match(r"^\+7\d{10}$", phone))


def _make_sign(params: dict, api_key: str) -> str:
    """
    Формирует подпись NotiSend:
    1. Сортируем параметры по ключу
    2. Берём только значения, соединяем через ';', добавляем api_key
    3. sha1 → md5
    """
    sorted_values = [str(v) for _, v in sorted(params.items())]
    step1 = ";".join(sorted_values) + ";" + api_key
    step2 = hashlib.sha1(step1.encode("utf-8")).hexdigest()
    sign  = hashlib.md5(step2.encode("utf-8")).hexdigest()
    return sign


async def _send_otp(phone: str, code: str) -> dict:
    """
    Отправляет OTP через NotiSend.ru в режиме Telegram Gateway.
    Сообщение содержит 6-значный код — NotiSend автоматически
    направит его в Telegram (настрой режим «Только Telegram» в ЛК NotiSend).
    """
    message_text = f"Ваш код подтверждения Профком ЧГУ: {code}"

    # Номер без '+' для API
    phone_digits = phone.lstrip("+")

    params = {
        "message":    message_text,
        "project":    NOTISEND_PROJECT,
        "recipients": phone_digits,
        "sender":     NOTISEND_SENDER,
    }
    sign = _make_sign(params, NOTISEND_API_KEY)
    params["sign"] = sign

    url = "https://sms.notisend.ru/api/message/send"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=params) as resp:
            try:
                return await resp.json(content_type=None)
            except Exception:
                text = await resp.text()
                return {"ok": False, "description": text}


# ─────────────────────────────────────────────────────────────────────────────
#  /start — главный вход
# ─────────────────────────────────────────────────────────────────────────────

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    await message.answer("👋", reply_markup=REMOVE_KEYBOARD)

    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()

    if student:
        is_admin = user_id in ADMIN_IDS
        return await message.answer("🏠 Главное меню:", reply_markup=main_menu_keyboard(is_admin))

    await message.answer(
        "🚀 *Добро пожаловать в Профком ЧГУ!*\n\nВыберите действие:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📱 Войти по номеру телефона",  callback_data="auth_phone")],
            [InlineKeyboardButton(text="🔢 Войти по баркоду",          callback_data="auth_barcode")],
            [InlineKeyboardButton(text="📝 Подать заявку на вступление", callback_data="request_registration")],
            [InlineKeyboardButton(text="🆘 Поддержка",                 callback_data="support_unreg")],
        ])
    )


# ─────────────────────────────────────────────────────────────────────────────
#  АВТОРИЗАЦИЯ ПО ТЕЛЕФОНУ (NotiSend → Telegram)
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
        return await message.answer(
            "❗ Неверный формат. Введите российский номер:\n+79001234567 или 89001234567"
        )

    # Проверяем наличие номера в базе
    with Session() as session:
        student = session.query(Student).filter_by(phone=phone).first()

    if not student:
        await state.clear()
        return await message.answer(
            f"❌ Номер {phone} не найден в базе.\n\n"
            "Если вы студент ЧГУ — подайте заявку на вступление:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📝 Подать заявку",      callback_data="request_registration")],
                [InlineKeyboardButton(text="🔢 Войти по баркоду",   callback_data="auth_barcode")],
                [InlineKeyboardButton(text="⬅️ Назад",              callback_data="back_to_start")],
            ])
        )

    # Генерируем 6-значный код
    code = str(random.randint(100000, 999999))
    user_id = message.from_user.id

    # Отправляем через NotiSend
    await message.answer("⏳ Отправляем код подтверждения в Telegram...")
    result = await _send_otp(phone, code)

    # NotiSend возвращает список сообщений при успехе
    success = isinstance(result, list) or (isinstance(result, dict) and result.get("id"))
    if not success:
        error = result.get("description", str(result)) if isinstance(result, dict) else str(result)
        return await message.answer(
            f"❌ Не удалось отправить код: {error}\n\n"
            "Попробуйте войти по баркоду:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔢 Войти по баркоду", callback_data="auth_barcode")]
            ])
        )

    # Сохраняем код в памяти
    _pending_codes[user_id] = {"code": code, "phone": phone, "student_id": student.id}

    await state.update_data(phone=phone, student_id=student.id)
    await state.set_state(PhoneAuthState.AWAITING_CODE)
    await message.answer(
        f"✅ Код отправлен в Telegram на номер {phone}!\n\n"
        "Введите 6-значный код:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Отправить снова", callback_data="resend_code")],
            [InlineKeyboardButton(text="⬅️ Назад",           callback_data="back_to_start")],
        ])
    )


@router.callback_query(F.data == "resend_code")
async def resend_code(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    phone = data.get("phone")
    if not phone:
        return await callback.answer("Начните авторизацию заново", show_alert=True)

    user_id = callback.from_user.id
    code = str(random.randint(100000, 999999))
    _pending_codes[user_id] = {**_pending_codes.get(user_id, {}), "code": code}

    await callback.answer("⏳ Отправляем...")
    await _send_otp(phone, code)
    await callback.message.answer("✅ Новый код отправлен! Введите его:")


@router.message(PhoneAuthState.AWAITING_CODE)
async def auth_code_receive(message: Message, state: FSMContext):
    code_input = (message.text or "").strip()
    if not re.match(r"^\d{6}$", code_input):
        return await message.answer("❗ Введите 6-значный код:")

    user_id = message.from_user.id
    pending = _pending_codes.get(user_id)

    if not pending or pending["code"] != code_input:
        return await message.answer(
            "❌ Неверный код. Попробуйте ещё раз или запросите новый.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Новый код", callback_data="resend_code")]
            ])
        )

    # Код верный — привязываем telegram_id
    student_id = pending["student_id"]
    _pending_codes.pop(user_id, None)

    with Session() as session:
        student = session.query(Student).get(student_id)
        if not student:
            await state.clear()
            return await message.answer("❌ Ошибка: студент не найден.")
        if student.telegram_id and student.telegram_id != user_id:
            await state.clear()
            return await message.answer(
                "⚠️ Этот номер уже привязан к другому аккаунту. Обратитесь в поддержку.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🆘 Поддержка", callback_data="support_unreg")]
                ])
            )
        student.telegram_id = user_id
        session.commit()

    await state.clear()
    is_admin = user_id in ADMIN_IDS
    await message.answer("✅ Авторизация прошла успешно!")
    await message.answer("🏠 Главное меню:", reply_markup=main_menu_keyboard(is_admin))


# ─────────────────────────────────────────────────────────────────────────────
#  АВТОРИЗАЦИЯ ПО БАРКОДУ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "auth_barcode")
async def auth_barcode_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(StudentVerificationState.AWAITING_BARCODE)
    await callback.message.answer(
        "🔢 Введите ваш баркод (13 цифр):\n\nПример: 2004111111111",
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
        return await message.answer("❗ Баркод должен содержать ровно 13 цифр")

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
        if student.telegram_id and student.telegram_id != user_id:
            return await message.answer(
                "⚠️ Баркод уже привязан к другому аккаунту.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🆘 Поддержка", callback_data="support_unreg")]
                ])
            )
        if not student.telegram_id:
            student.telegram_id = user_id
            session.commit()

    await state.clear()
    is_admin = user_id in ADMIN_IDS
    await message.answer("✅ Готово! Ты успешно вошёл.")
    await message.answer("🏠 Главное меню:", reply_markup=main_menu_keyboard(is_admin))


# ─────────────────────────────────────────────────────────────────────────────
#  ЗАЯВКА НА ВСТУПЛЕНИЕ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "request_registration")
async def start_reg_request(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(RegistrationRequestState.AWAITING_FIO)
    await callback.message.answer(
        "📝 *Заявка на вступление в Профком ЧГУ*\n\n"
        "Тогда напишите нам ваше:\n\n"
        "*1. ФИО* (полностью, например: Иванов Иван Иванович):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_start")]
        ])
    )


@router.message(RegistrationRequestState.AWAITING_FIO)
async def reg_request_fio(message: Message, state: FSMContext):
    await state.update_data(full_name=message.text.strip())
    await message.answer("*2. Дата рождения* (например: 01.01.2000):", parse_mode="Markdown")
    await state.set_state(RegistrationRequestState.AWAITING_BIRTH_DATE)


@router.message(RegistrationRequestState.AWAITING_BIRTH_DATE)
async def reg_request_birth(message: Message, state: FSMContext):
    await state.update_data(birth_date=message.text.strip())
    await message.answer("*3. Факультет / Институт:*", parse_mode="Markdown")
    await state.set_state(RegistrationRequestState.AWAITING_FACULTY)


@router.message(RegistrationRequestState.AWAITING_FACULTY)
async def reg_request_faculty(message: Message, state: FSMContext):
    await state.update_data(faculty=message.text.strip())
    await message.answer("*4. Номер телефона* (или «нет»):", parse_mode="Markdown")
    await state.set_state(RegistrationRequestState.AWAITING_PHONE)


@router.message(RegistrationRequestState.AWAITING_PHONE)
async def reg_request_phone(message: Message, state: FSMContext, bot: Bot):
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
        "Мы вас внесём в базу приложения и зарезервируем под вас баркод, "
        "после чего сообщим цифры.\n\nОжидайте ответа администратора.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Написать вопрос", callback_data=f"reg_chat_{req_id}")]
        ])
    )

    # Уведомляем модераторов
    from handlers.support import _get_mods
    with Session() as session:
        mods = _get_mods(session)

    notif = (
        f"📋 *Новая заявка на регистрацию #{req_id}*\n\n"
        f"👤 {data['full_name']}\n"
        f"📅 Дата рождения: {data.get('birth_date', '—')}\n"
        f"🏛 Факультет: {data['faculty']}\n"
        f"📱 Телефон: {phone or '—'}\n"
        f"🆔 Telegram ID: {user_id}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Открыть заявку", callback_data=f"view_reg_req_{req_id}")]
    ])
    for mod_id, _ in mods:
        try: await bot.send_message(mod_id, notif, parse_mode="Markdown", reply_markup=kb)
        except Exception: pass


@router.callback_query(F.data.startswith("reg_chat_"))
async def reg_chat_open(callback: CallbackQuery, state: FSMContext):
    req_id = int(callback.data.split("_")[2])
    await state.update_data(reg_reply_req_id=req_id)
    from states import RegRequestReplyState
    await state.set_state(RegRequestReplyState.AWAITING_MESSAGE)
    await callback.message.answer(
        "✏️ Напишите ваш вопрос или дополнение:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_start")]
        ])
    )


# ─────────────────────────────────────────────────────────────────────────────
#  НАВИГАЦИЯ
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "back_to_start")
async def back_to_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()

    try: await callback.message.delete()
    except Exception: pass

    if student:
        is_admin = user_id in ADMIN_IDS
        return await callback.message.answer("🏠 Главное меню:", reply_markup=main_menu_keyboard(is_admin))

    await callback.message.answer(
        "🚀 *Добро пожаловать в Профком ЧГУ!*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📱 Войти по номеру телефона",  callback_data="auth_phone")],
            [InlineKeyboardButton(text="🔢 Войти по баркоду",          callback_data="auth_barcode")],
            [InlineKeyboardButton(text="📝 Подать заявку",             callback_data="request_registration")],
            [InlineKeyboardButton(text="🆘 Поддержка",                 callback_data="support_unreg")],
        ])
    )
