# main.py
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from config import BOT_TOKEN
from models import Base
from database import engine

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
