# handlers/notifications.py
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command

from database import Session
from models import Student

router = Router()


@router.message(Command("notify_test"))
async def test_notification(message: Message):
    user_id = message.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        if not student:
            return await message.answer("❌ Ты не зарегистрирован.")

    await message.answer(
        f"📬 Привет, {student.full_name}!\n\n"
        "Это тестовое уведомление — всё работает корректно."
    )
