# states.py
from aiogram.fsm.state import StatesGroup, State

class TaskState(StatesGroup):
    AWAITING_TITLE = State()
    AWAITING_DESCRIPTION = State()
    AWAITING_POINTS = State()
    AWAITING_CHECK_TYPE = State()
    AWAITING_CORRECT_ANSWER = State()
    AWAITING_PROOF_TEXT = State()
    AWAITING_PROOF_FILE = State()
    AWAITING_DEADLINE = State()
    AWAITING_SHOW_DEADLINE = State()
    waiting_answer = State()
    waiting_proof = State()

class ItemCreateState(StatesGroup):
    AWAITING_NAME = State()
    AWAITING_DESCRIPTION = State()
    AWAITING_PRICE = State()
    AWAITING_STOCK = State()
    AWAITING_IMAGE = State()

class ItemEditState(StatesGroup):
    AWAITING_FIELD = State()
    AWAITING_NEW_VALUE = State()
    editing_name = State()
    editing_description = State()
    editing_price = State()
    editing_stock = State()
    editing_photo = State()

class StudentVerificationState(StatesGroup):
    AWAITING_BARCODE = State()

class StudentSearchState(StatesGroup):
    AWAITING_INPUT = State()

class StudentEditState(StatesGroup):
    AWAITING_FIELD = State()
    AWAITING_VALUE = State()

class ImportState(StatesGroup):
    AWAITING_FILE = State()

class SupportState(StatesGroup):
    AWAITING_MESSAGE = State()
    AWAITING_REPLY = State()

class AdminMsgState(StatesGroup):
    AWAITING_MESSAGE = State()

# ── Мероприятия ──────────────────────────────────────────────────────────────
class EventCreateState(StatesGroup):
    AWAITING_TITLE = State()
    AWAITING_POINTS = State()

class LectureCreateState(StatesGroup):
    AWAITING_TITLE = State()
    AWAITING_POINTS = State()

class EventScanState(StatesGroup):
    """Режим сканирования участников / лекций."""
    REGISTER_PARTICIPANTS = State()   # регистрация участников на мероприятие
    SCAN_LECTURE = State()            # сканирование посещаемости лекции
