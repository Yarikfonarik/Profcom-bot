# main.py
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from models import Base
from database import engine

from handlers import (
    navigation,
    registration,
    tasks,
    shop,
    statistics,
    events,
    admin_students,
    notifications,
    support,
)


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    Base.metadata.create_all(engine)

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(registration.router)
    dp.include_router(navigation.router)
    dp.include_router(support.router)
    dp.include_router(tasks.router)
    dp.include_router(shop.router)
    dp.include_router(statistics.router)
    dp.include_router(events.router)
    dp.include_router(admin_students.router)
    dp.include_router(notifications.router)

    logging.info("Бот запущен ✅")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
