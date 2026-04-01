# main.py
import asyncio
import logging

import aiohttp
from aiohttp_socks import ProxyConnector
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.session.aiohttp import AiohttpSession

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

PROXIES = [
    "socks5://173.249.5.133:1080",
    "socks5://37.18.73.60:5566",
    "socks5://206.123.156.187:5886",
    "socks5://206.123.156.231:10611",
    "socks5://85.198.96.242:1080",
]


class ProxyAiohttpSession(AiohttpSession):
    def __init__(self, proxy: str, **kwargs):
        super().__init__(**kwargs)
        self._proxy_url = proxy

    async def create_session(self) -> aiohttp.ClientSession:
        connector = ProxyConnector.from_url(self._proxy_url, rdns=True)
        return aiohttp.ClientSession(connector=connector)


async def find_best_proxy() -> str | None:
    for proxy in PROXIES:
        try:
            connector = ProxyConnector.from_url(proxy, rdns=True)
            async with aiohttp.ClientSession(connector=connector) as s:
                async with s.get("https://api.telegram.org", timeout=aiohttp.ClientTimeout(total=8)):
                    logging.info(f"✅ Прокси: {proxy}")
                    return proxy
        except Exception:
            logging.warning(f"❌ {proxy}")
    return None


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    Base.metadata.create_all(engine)

    proxy = await find_best_proxy()
    if proxy:
        session = ProxyAiohttpSession(proxy=proxy)
        bot = Bot(token=BOT_TOKEN, session=session)
    else:
        logging.warning("Прокси не найден, подключаемся напрямую")
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
