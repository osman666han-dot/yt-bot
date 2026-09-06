from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command

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
