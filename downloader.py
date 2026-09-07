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
    format_id: str       # для видео здесь хранится высота как строка (напр. "720"), для аудио — "bestaudio"
    label: str          # что показываем на кнопке, напр. "720p" или "MP3 (аудио)"
    kind: str           # "video" или "audio"
    filesize_mb: float | None


def _base_opts() -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    if PROXY_URL:
        opts["proxy"] = PROXY_URL
    if YTDLP_COOKIES_CONTENT:
        opts["cookiefile"] = _COOKIES_FILE
    return opts


async def list_formats(url: str) -> list[FormatOption]:
    """Возвращает доступные варианты: видео до MAX_QUALITY + аудио-mp3."""
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

    # аудио-опция всегда одна, качество не выбираем
    options.append(FormatOption(
        format_id="bestaudio",
        label="MP3 (аудио)",
        kind="audio",
        filesize_mb=None,
    ))
    return options


async def download(url: str, format_id: str, kind: str) -> str:
    """Скачивает и возвращает путь к файлу на диске. Вызывающий код обязан удалить файл после отправки."""
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
        height = format_id  # тут это высота, напр. "720"
        opts["format"] = (
            f"bestvideo[height<={height}][vcodec^=avc1]+bestaudio[acodec^=mp4a]"
            f"/best[height<={height}][vcodec^=avc1]"
            f"/bestvideo[height<={height}]+bestaudio/best[height<={height}]"
            f"/bestvideo+bestaudio/best"
        )
        opts["merge_output_format"] = "mp4"
        opts["postprocessor_args"] = {"ffmpeg": ["-movflags", "+faststart"]}

    def _run():
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

    try:
        await asyncio.wait_for(asyncio.to_thread(_run), timeout=DOWNLOAD_TIMEOUT_SEC)
    except asyncio.TimeoutError:
        raise DownloadError("Скачивание заняло слишком много времени, попробуй другое качество или видео короче.")
    except yt_dlp.utils.DownloadError as e:
        raise DownloadError(_friendly_error(str(e)))

    # находим итоговый файл (расширение проставит yt-dlp/ffmpeg)
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


def get_video_metadata(path: str) -> dict | None:
    """duration/width/height через ffprobe — нужно Telegram для показа видео плеером сразу, без ожидания скачивания."""
    import json
    import subprocess
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", path,
            ],
            capture_output=True, text=True, timeout=15,
        )
        data = json.loads(result.stdout)
        duration = int(float(data.get("format", {}).get("duration", 0)))
        width = height = None
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                width = stream.get("width")
                height = stream.get("height")
                break
        return {"duration": duration, "width": width, "height": height}
    except Exception:
        return None


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
