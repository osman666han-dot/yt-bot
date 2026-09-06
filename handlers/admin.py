import asyncio

from aiogram import Router, F, Bot
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

import db
from config import ADMIN_IDS

router = Router()


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not _is_admin(message.from_user.id):
        return
    stats = db.get_stats()
    lines = [
        f"Всего скачано: {stats['total']}",
        f"Сегодня: {stats['today']}",
        "",
        "Топ юзеров:",
    ]
    for user_id, username, cnt in stats["top_users"]:
        uname = f"@{username}" if username else str(user_id)
        lines.append(f"  {uname} — {cnt}")
    await message.answer("\n".join(lines))


@router.message(Command("users"))
async def cmd_users(message: Message):
    if not _is_admin(message.from_user.id):
        return
    users = db.get_all_users()
    if not users:
        await message.answer("Юзеров пока нет.")
        return

    lines = [f"Всего юзеров: {len(users)}", ""]
    for user_id, username, blocked, first_seen, downloads_count in users:
        uname = f"@{username}" if username else str(user_id)
        status = "🚫 заблокировал" if blocked else "✅"
        lines.append(f"{uname} (id {user_id}) — {downloads_count} скачиваний — {status}")

    # Telegram режет сообщения на 4096 символов, бьём на части
    text = "\n".join(lines)
    for i in range(0, len(text), 4000):
        await message.answer(text[i:i + 4000])


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, bot: Bot):
    if not _is_admin(message.from_user.id):
        return
    text = message.text.partition(" ")[2].strip()
    if not text:
        await message.answer("Использование: /broadcast <текст сообщения>")
        return

    user_ids = db.get_active_user_ids()
    await message.answer(f"Начинаю рассылку на {len(user_ids)} юзеров...")

    sent, blocked, failed = 0, 0, 0
    for user_id in user_ids:
        try:
            await bot.send_message(user_id, text)
            sent += 1
        except TelegramForbiddenError:
            db.mark_blocked(user_id, True)
            blocked += 1
        except TelegramBadRequest:
            failed += 1
        await asyncio.sleep(0.05)  # защита от лимитов Telegram на частоту сообщений

    await message.answer(
        f"Готово. Доставлено: {sent}. Заблокировали бота: {blocked}. Ошибок: {failed}."
    )


@router.message(Command("logs"))
async def cmd_logs(message: Message):
    if not _is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Использование: /logs <user_id>")
        return
    try:
        target_id = int(parts[1])
    except ValueError:
        await message.answer("user_id должен быть числом.")
        return

    rows = db.get_user_history(target_id)
    if not rows:
        await message.answer("Нет записей по этому юзеру.")
        return

    lines = [f"История {target_id}:"]
    for url, fmt, size, status, created_at in rows:
        size_str = f"{size} МБ" if size else "-"
        lines.append(f"{created_at} | {fmt} | {size_str} | {status} | {url}")
    await message.answer("\n".join(lines))
