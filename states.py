# states.py
from aiogram.fsm.state import StatesGroup, State

class UploadState(StatesGroup):
    AWAITING_TITLE = State()
    AWAITING_POINTS = State()
    AWAITING_FILE = State()

class TaskState(StatesGroup):
    AWAITING_TITLE = State()
    AWAITING_DESCRIPTION = State()
    AWAITING_POINTS = State()
    AWAITING_CHECK_TYPE = State()
    AWAITING_CORRECT_ANSWER = State()
    AWAITING_PROOF_TEXT = State()
    AWAITING_PROOF_FILE = State()
    AWAITING_DEADLINE = State()   # новое состояние для дедлайна
    waiting_answer = State()
    waiting_proof = State()

class ItemCreateState(StatesGroup):
    AWAITING_NAME = State()
    AWAITING_DESCRIPTION = State()
    AWAITING_PRICE = State()
    AWAITING_IMAGE = State()
    AWAITING_STOCK = State()

class ItemEditState(StatesGroup):
    AWAITING_FIELD = State()
    AWAITING_NEW_VALUE = State()
    editing_name = State()
    editing_description = State()
    editing_price = State()
    editing_stock = State()
    editing_photo = State()

class EventUploadState(StatesGroup):
    AWAITING_TITLE = State()
    AWAITING_POINTS = State()
    AWAITING_FILE = State()

class ManualBarcodeState(StatesGroup):
    AWAITING_EVENT_ID = State()
    AWAITING_BARCODE = State()

class StudentVerificationState(StatesGroup):
    AWAITING_BARCODE = State()

class StudentSearchState(StatesGroup):
    AWAITING_INPUT = State()

class StudentEditState(StatesGroup):
    AWAITING_FIELD = State()
    AWAITING_VALUE = State()

class ImportState(StatesGroup):
    AWAITING_FILE = State()
