import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

import db
from config import BOT_TOKEN, LOCAL_BOT_API_URL
from handlers import user, admin

logging.basicConfig(level=logging.INFO)


def _build_bot() -> Bot:
    if LOCAL_BOT_API_URL:
        # локальный Bot API сервер -> лимит на файлы до 2 ГБ вместо 50 МБ
        session = AiohttpSession(
            api=TelegramAPIServer.from_base(LOCAL_BOT_API_URL)
        )
        return Bot(token=BOT_TOKEN, session=session)
    return Bot(token=BOT_TOKEN)


async def main():
    db.init_db()

    bot = _build_bot()
    dp = Dispatcher()
    dp.include_router(admin.router)
    dp.include_router(user.router)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
