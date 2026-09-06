from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, LabeledPrice
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

import db
import downloader
from config import FREE_DOWNLOADS_PER_DAY, EXTRA_BATCH_SIZE, STARS_PRICE_PER_EXTRA_BATCH, COOLDOWN_SECONDS

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message):
    db.register_user(message.from_user.id, message.from_user.username)
    await message.answer(
        "Бот для бесплатного скачивания видео с YouTube.\n"
        "От проекта @kolokotol\n\n"
        "Просто пришли ссылку боту, выбери качество и жди скачивания."
    )


@router.message(F.text.contains("youtu"))
async def handle_link(message: Message):
    user_id = message.from_user.id
    db.register_user(user_id, message.from_user.username)

    since_last = db.seconds_since_last_download(user_id)
    if since_last is not None and since_last < COOLDOWN_SECONDS:
        wait_min = int((COOLDOWN_SECONDS - since_last) // 60) + 1
        await message.answer(f"Подожди ещё {wait_min} мин. перед следующим скачиванием.")
        return

    remaining_free = FREE_DOWNLOADS_PER_DAY - db.count_downloads_today(user_id)
    extra = db.get_extra_credits(user_id)

    if remaining_free <= 0 and extra <= 0:
        await _offer_payment(message)
        return

    await message.answer("Смотрю доступные форматы...")

    try:
        options = await downloader.list_formats(message.text.strip())
    except downloader.DownloadError as e:
        await message.answer(str(e))
        return

    key = f"{user_id}:{message.message_id}"
    options_dicts = [
        {"format_id": o.format_id, "label": o.label, "kind": o.kind, "filesize_mb": o.filesize_mb}
        for o in options
    ]
    db.save_pending(key, user_id, message.text.strip(), options_dicts)

    kb = InlineKeyboardBuilder()
    for i, opt in enumerate(options):
        size = f" (~{opt.filesize_mb} МБ)" if opt.filesize_mb else ""
        kb.button(text=f"{opt.label}{size}", callback_data=f"fmt:{key}:{i}")
    kb.adjust(2)

    await message.answer("Выбери формат:", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("fmt:"))
async def handle_format_choice(callback: CallbackQuery):
    _, key, idx = callback.data.split(":", 2)
    user_id = callback.from_user.id

    url, options = db.get_pending(key)
    if url is None or options is None:
        await callback.answer("Сессия устарела, пришли ссылку заново.", show_alert=True)
        return

    opt = options[int(idx)]  # dict: format_id, label, kind, filesize_mb

    # повторная проверка лимита (мог исчерпаться между показом кнопок и нажатием)
    remaining_free = FREE_DOWNLOADS_PER_DAY - db.count_downloads_today(user_id)
    used_extra = False
    if remaining_free <= 0:
        if db.get_extra_credits(user_id) <= 0:
            await callback.message.answer("Лимит закончился, пока ты выбирал.")
            await _offer_payment(callback.message)
            return
        used_extra = True

    await callback.message.edit_text(f"Качаю в {opt['label']}...")

    path = None
    try:
        path = await downloader.download(url, opt["format_id"], opt["kind"])
        size_mb = round(__import__("os").path.getsize(path) / (1024 * 1024), 1)

        if opt["kind"] == "audio":
            await callback.message.answer_audio(open(path, "rb"))
        else:
            await callback.message.answer_video(open(path, "rb"))

        db.log_download(user_id, callback.from_user.username, url, opt["label"], size_mb, "ok")
        if used_extra:
            db.spend_extra_credit(user_id)

    except downloader.DownloadError as e:
        db.log_download(user_id, callback.from_user.username, url, opt["label"], None, "error", str(e))
        await callback.message.answer(str(e))
    finally:
        if path:
            downloader.cleanup(path)
        db.delete_pending(key)


async def _offer_payment(message: Message):
    await message.bot.send_invoice(
        chat_id=message.chat.id,
        title=f"+{EXTRA_BATCH_SIZE} скачиваний",
        description=f"Ещё {EXTRA_BATCH_SIZE} скачиваний сверх бесплатного дневного лимита",
        payload="extra_batch",
        currency="XTR",
        prices=[LabeledPrice(label=f"+{EXTRA_BATCH_SIZE} скачиваний", amount=STARS_PRICE_PER_EXTRA_BATCH)],
    )


@router.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query):
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def process_successful_payment(message: Message):
    db.add_extra_credits(message.from_user.id, EXTRA_BATCH_SIZE)
    await message.answer(f"Готово! Начислено +{EXTRA_BATCH_SIZE} скачиваний.")
