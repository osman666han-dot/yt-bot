import os
import uuid
import asyncio
from dataclasses import dataclass

import yt_dlp

from config import TMP_DIR, DOWNLOAD_TIMEOUT_SEC, MAX_QUALITY, PROXY_URL, YTDLP_COOKIES_CONTENT

os.makedirs(TMP_DIR, exist_ok=True)

_COOKIES_FILE = os.path.join(TMP_DIR, "cookies.txt")
if YTDLP_COOKIES_CONTENT:
    with open(_COOKIES_FILE, "w", encoding="utf-8") as f:
        f.write(YTDLP_COOKIES_CONTENT)


class DownloadError(Exception):
    """Понятная юзеру ошибка (приватное видео, гео-блок, удалено и т.п.)"""


@dataclass
class FormatOption:
    format_id: str
    label: str
    kind: str
    filesize_mb: float | None


def _base_opts() -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }
    if PROXY_URL:
        opts["proxy"] = PROXY_URL
    if YTDLP_COOKIES_CONTENT:
        opts["cookiefile"] = _COOKIES_FILE
    return opts


async def list_formats(url: str) -> list[FormatOption]:
    def _extract():
        opts = _base_opts()
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        info = await asyncio.to_thread(_extract)
    except yt_dlp.utils.DownloadError as e:
        raise DownloadError(_friendly_error(str(e)))

    options: list[FormatOption] = []
    seen_heights = set()

    for f in info.get("formats", []):
        height = f.get("height")
        if not height or height > int(MAX_QUALITY):
            continue
        if f.get("vcodec") == "none":
            continue
        if height in seen_heights:
            continue
        seen_heights.add(height)
        size = f.get("filesize") or f.get("filesize_approx")
        options.append(FormatOption(
            format_id=str(height),
            label=f"{height}p",
            kind="video",
            filesize_mb=round(size / (1024 * 1024), 1) if size else None,
        ))

    options.sort(key=lambda o: int(o.label.replace("p", "")), reverse=True)

    options.append(FormatOption(
        format_id="bestaudio",
        label="MP3 (аудио)",
        kind="audio",
        filesize_mb=None,
    ))
    return options


async def download(url: str, format_id: str, kind: str) -> str:
    file_id = uuid.uuid4().hex
    out_template = os.path.join(TMP_DIR, f"{file_id}.%(ext)s")

    opts = _base_opts()
    opts["outtmpl"] = out_template

    if kind == "audio":
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
        }]
    else:
        height = format_id
        opts["format"] = (
            f"bestvideo[height<={height}]+bestaudio/best[height<={height}]"
            f"/bestvideo+bestaudio/best"
        )
        opts["merge_output_format"] = "mp4"

    def _run():
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

    try:
        await asyncio.wait_for(asyncio.to_thread(_run), timeout=DOWNLOAD_TIMEOUT_SEC)
    except asyncio.TimeoutError:
        raise DownloadError("Скачивание заняло слишком много времени, попробуй другое качество или видео короче.")
    except yt_dlp.utils.DownloadError as e:
        raise DownloadError(_friendly_error(str(e)))

    for fname in os.listdir(TMP_DIR):
        if fname.startswith(file_id):
            return os.path.join(TMP_DIR, fname)

    raise DownloadError("Файл не найден после скачивания, попробуй ещё раз.")


def cleanup(path: str):
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _friendly_error(raw: str) -> str:
    raw_low = raw.lower()
    if "private" in raw_low:
        return "Это приватное видео, доступа нет."
    if "age" in raw_low and "restrict" in raw_low:
        return "Видео с возрастным ограничением, бот не может его скачать."
    if "unavailable" in raw_low or "removed" in raw_low:
        return "Видео недоступно или удалено."
    if "geo" in raw_low or "country" in raw_low:
        return "Видео недоступно в регионе сервера."
    return "Не получилось скачать это видео. Попробуй другую ссылку."
