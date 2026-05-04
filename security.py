# security.py — централизованный модуль безопасности бота Профком ЧГУ
import secrets
import time
import logging
from functools import wraps
from typing import Optional

from aiogram.types import Message, CallbackQuery

logger = logging.getLogger("security")

# ─────────────────────────────────────────────────────────────────────────────
#  КОНСТАНТЫ
# ─────────────────────────────────────────────────────────────────────────────

OTP_TTL_SECONDS      = 300   # Код действует 5 минут
OTP_MAX_ATTEMPTS     = 5     # Макс. попыток ввода кода
OTP_RESEND_COOLDOWN  = 60    # Секунд между повторной отправкой

RATE_LIMIT_WINDOW    = 60    # Окно rate-limit (секунды)
RATE_LIMIT_MAX_CALLS = 30    # Макс. запросов за окно на одного пользователя

# Максимальная длина текстовых полей (символы)
MAX_LEN = {
    "full_name":    100,
    "faculty":      120,
    "description":  1000,
    "how_to_join":  500,
    "pickup_info":  300,
    "title":        200,
    "text_proof":   2000,
    "support_msg":  3000,
    "news_text":    4000,
    "generic":      500,
}

# ─────────────────────────────────────────────────────────────────────────────
#  ХРАНИЛИЩЕ (in-memory, достаточно для одного процесса)
# ─────────────────────────────────────────────────────────────────────────────

# { user_id: {"code": str, "phone": str, "student_id": int,
#             "issued_at": float, "attempts": int, "last_resend": float} }
_pending_otp: dict[int, dict] = {}

# { user_id: {"count": int, "window_start": float} }
_rate_counters: dict[int, dict] = {}


# ─────────────────────────────────────────────────────────────────────────────
#  OTP
# ─────────────────────────────────────────────────────────────────────────────

def otp_generate() -> str:
    """Криптографически безопасный 6-значный OTP."""
    return f"{secrets.randbelow(1_000_000):06d}"


def otp_create(user_id: int, phone: str, student_id: int) -> str:
    """Создаёт и сохраняет OTP. Возвращает код."""
    code = otp_generate()
    _pending_otp[user_id] = {
        "code":        code,
        "phone":       phone,
        "student_id":  student_id,
        "issued_at":   time.monotonic(),
        "attempts":    0,
        "last_resend": time.monotonic(),
    }
    logger.info("OTP issued for user_id=%s phone=%s", user_id, phone)
    return code


def otp_can_resend(user_id: int) -> tuple[bool, int]:
    """
    Проверяет можно ли переотправить код.
    Возвращает (разрешено, секунд_осталось).
    """
    entry = _pending_otp.get(user_id)
    if not entry:
        return False, 0
    elapsed = time.monotonic() - entry["last_resend"]
    remaining = int(OTP_RESEND_COOLDOWN - elapsed)
    return remaining <= 0, max(0, remaining)


def otp_refresh(user_id: int) -> Optional[str]:
    """
    Обновляет OTP (новый код + сброс таймера).
    Возвращает новый код или None если нет активной сессии.
    """
    entry = _pending_otp.get(user_id)
    if not entry:
        return None
    new_code = otp_generate()
    entry["code"]        = new_code
    entry["issued_at"]   = time.monotonic()
    entry["attempts"]    = 0
    entry["last_resend"] = time.monotonic()
    logger.info("OTP refreshed for user_id=%s", user_id)
    return new_code


def otp_verify(user_id: int, code_input: str) -> tuple[bool, str]:
    """
    Проверяет код.
    Возвращает (успех, сообщение_об_ошибке).
    """
    entry = _pending_otp.get(user_id)

    if not entry:
        return False, "Сессия устарела. Начните заново."

    # Истёк TTL
    if time.monotonic() - entry["issued_at"] > OTP_TTL_SECONDS:
        _pending_otp.pop(user_id, None)
        return False, f"Код истёк (действует {OTP_TTL_SECONDS // 60} мин). Запросите новый."

    # Превышено число попыток
    if entry["attempts"] >= OTP_MAX_ATTEMPTS:
        _pending_otp.pop(user_id, None)
        return False, "Слишком много неверных попыток. Запросите новый код."

    entry["attempts"] += 1

    # Сравнение через secrets.compare_digest — защита от timing-атак
    if not secrets.compare_digest(entry["code"], code_input):
        left = OTP_MAX_ATTEMPTS - entry["attempts"]
        logger.warning("Wrong OTP attempt for user_id=%s (left=%s)", user_id, left)
        return False, f"❌ Неверный код. Осталось попыток: {left}"

    # Успех
    _pending_otp.pop(user_id, None)
    logger.info("OTP verified OK for user_id=%s", user_id)
    return True, ""


def otp_get_meta(user_id: int) -> Optional[dict]:
    """Возвращает метаданные OTP (phone, student_id) без кода."""
    entry = _pending_otp.get(user_id)
    if not entry:
        return None
    return {"phone": entry["phone"], "student_id": entry["student_id"]}


# ─────────────────────────────────────────────────────────────────────────────
#  RATE LIMITER
# ─────────────────────────────────────────────────────────────────────────────

def rate_limit_check(user_id: int) -> bool:
    """
    Возвращает True если пользователь превысил лимит запросов.
    """
    now = time.monotonic()
    rec = _rate_counters.get(user_id)

    if rec is None or now - rec["window_start"] > RATE_LIMIT_WINDOW:
        _rate_counters[user_id] = {"count": 1, "window_start": now}
        return False

    rec["count"] += 1
    if rec["count"] > RATE_LIMIT_MAX_CALLS:
        logger.warning("Rate limit triggered for user_id=%s (count=%s)", user_id, rec["count"])
        return True
    return False


def rate_limited(fn):
    """
    Декоратор: блокирует хендлер если пользователь флудит.
    Работает с Message и CallbackQuery.
    """
    @wraps(fn)
    async def wrapper(*args, **kwargs):
        target = next((a for a in args if isinstance(a, (Message, CallbackQuery))), None)
        if target is None:
            return await fn(*args, **kwargs)
        uid = target.from_user.id
        if rate_limit_check(uid):
            if isinstance(target, CallbackQuery):
                await target.answer("⏳ Слишком много запросов. Подождите минуту.", show_alert=True)
            else:
                await target.answer("⏳ Слишком много запросов. Подождите минуту.")
            return
        return await fn(*args, **kwargs)
    return wrapper


# ─────────────────────────────────────────────────────────────────────────────
#  ВАЛИДАЦИЯ ВВОДА
# ─────────────────────────────────────────────────────────────────────────────

def validate_length(text: str, field: str = "generic") -> tuple[bool, str]:
    """
    Проверяет длину поля.
    Возвращает (валидно, сообщение).
    """
    max_len = MAX_LEN.get(field, MAX_LEN["generic"])
    if len(text) > max_len:
        return False, f"❗ Слишком длинный текст (максимум {max_len} символов, у вас {len(text)})."
    if not text.strip():
        return False, "❗ Поле не может быть пустым."
    return True, ""


def sanitize_text(text: str) -> str:
    """
    Базовая очистка текста: убирает нулевые байты и обрезает пробелы.
    """
    return text.replace("\x00", "").strip()


# ─────────────────────────────────────────────────────────────────────────────
#  БЕЗОПАСНЫЙ ПАРСИНГ callback.data
# ─────────────────────────────────────────────────────────────────────────────

def safe_int(value: str, default: int = 0) -> int:
    """
    Безопасное приведение строки к int.
    Никогда не выбрасывает исключение.
    """
    try:
        return int(value)
    except (ValueError, TypeError):
        logger.warning("safe_int failed: %r", value)
        return default


def parse_callback_ints(data: str, sep: str = "_", indices: list[int] = None) -> Optional[list[int]]:
    """
    Парсит callback_data и возвращает список int-значений по заданным индексам.
    Возвращает None если хотя бы один индекс не распарсился.
    """
    parts = data.split(sep)
    result = []
    for i in indices or []:
        if i >= len(parts):
            return None
        try:
            result.append(int(parts[i]))
        except ValueError:
            return None
    return result
