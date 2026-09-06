import asyncio
import logging
import time

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

import db
from config import (
    BOT_TOKEN, LOCAL_BOT_API_URL, ADMIN_IDS,
    ERROR_RATE_CHECK_INTERVAL_SEC, ERROR_RATE_THRESHOLD_PERCENT,
    ERROR_RATE_MIN_SAMPLE, ERROR_RATE_ALERT_COOLDOWN_SEC,
)
from handlers import user, admin

logging.basicConfig(level=logging.INFO)


def _build_bot() -> Bot:
    if LOCAL_BOT_API_URL:
        session = AiohttpSession(
            api=TelegramAPIServer.from_base(LOCAL_BOT_API_URL)
        )
        return Bot(token=BOT_TOKEN, session=session)
    return Bot(token=BOT_TOKEN)


async def _error_rate_watcher(bot: Bot):
    last_alert_at = 0.0
    while True:
        await asyncio.sleep(ERROR_RATE_CHECK_INTERVAL_SEC)
        try:
            total, errors, pct = db.get_error_rate_last_hour()
            if total < ERROR_RATE_MIN_SAMPLE or pct < ERROR_RATE_THRESHOLD_PERCENT:
                continue
            if time.monotonic() - last_alert_at < ERROR_RATE_ALERT_COOLDOWN_SEC:
                continue

            last_alert_at = time.monotonic()
            text = (
                f"⚠️ Высокий процент ошибок скачивания за последний час: {pct}% "
                f"({errors} из {total})."
            )
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(admin_id, text)
                except (TelegramForbiddenError, TelegramBadRequest):
                    pass
        except Exception:
            logging.exception("Ошибка в error_rate_watcher")


async def main():
    db.init_db()

    bot = _build_bot()
    dp = Dispatcher()
    dp.include_router(admin.router)
    dp.include_router(user.router)

    asyncio.create_task(_error_rate_watcher(bot))

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
