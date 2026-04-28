# main.py
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from sqlalchemy import text

from config import BOT_TOKEN
from models import Base
from database import engine, Session


def _fix_sequences():
    """Восстанавливает sequence PostgreSQL после прямого SQL-импорта данных."""
    tables = [
        'students', 'tasks', 'task_verifications', 'merchandise',
        'purchases', 'events', 'event_participants', 'lectures',
        'lecture_scans', 'support_tickets', 'support_messages',
        'registration_requests', 'reg_request_messages',
        'unmatched_barcodes', 'attendance',
    ]
    with Session() as session:
        for table in tables:
            try:
                session.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {table}), 1))"
                ))
            except Exception:
                pass
        try:
            session.commit()
        except Exception:
            pass


def _migrate_schema():
    """Добавляет новые колонки в существующие таблицы (safe migration)."""
    with Session() as session:
        try:
            session.execute(text(
                "ALTER TABLE events ADD COLUMN IF NOT EXISTS pickup_info TEXT"
            ))
            session.commit()
        except Exception:
            pass

from handlers import (
    navigation, registration, tasks, shop,
    statistics, events, admin_students, notifications, support,
    reg_requests, news,
)


async def set_commands(bot: Bot):
    await bot.set_my_commands([
        BotCommand(command="start",  description="🚀 Начало"),
        BotCommand(command="menu",   description="🏠 Главное меню"),
        BotCommand(command="profile",description="👤 Профиль"),
        BotCommand(command="tasks",  description="📄 Задания"),
        BotCommand(command="shop",   description="🛍 Магазин"),
        BotCommand(command="events", description="📥 Мероприятия"),
        BotCommand(command="help",   description="🆘 Поддержка"),
    ])


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    Base.metadata.create_all(engine)
    _fix_sequences()     # Сбрасываем sequence после прямых SQL-импортов
    _migrate_schema()    # Добавляем новые колонки

    bot = Bot(token=BOT_TOKEN)
    dp  = Dispatcher(storage=MemoryStorage())

    dp.include_router(registration.router)
    dp.include_router(navigation.router)
    dp.include_router(events.router)
    dp.include_router(tasks.router)
    dp.include_router(shop.router)
    dp.include_router(statistics.router)
    dp.include_router(admin_students.router)
    dp.include_router(notifications.router)
    dp.include_router(reg_requests.router)
    dp.include_router(news.router)
    dp.include_router(support.router)   # ПОСЛЕДНИМ — содержит catch-all хендлер

    await set_commands(bot)
    logging.info("Бот запущен ✅")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
