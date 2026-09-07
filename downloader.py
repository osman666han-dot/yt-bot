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
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
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
    """Скачивает и возвращает путь к файлу на диске. Вызывающий код обязан удалить файл после отправки.

    Через прокси идёт только запрос метаданных (мелкий, килобайты).
    Сами байты видео/аудио качаются напрямую с CDN YouTube, без прокси — это бесплатно
    и не тратит платный трафик прокси-провайдера.
    """
    def _extract():
        opts = _base_opts()  # прокси + куки — только для этого запроса метаданных
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        info = await asyncio.to_thread(_extract)
    except yt_dlp.utils.DownloadError as e:
        raise DownloadError(_friendly_error(str(e)))

    formats = info.get("formats", [])
    file_id = uuid.uuid4().hex

    try:
        if kind == "audio":
            audio_fmt = _pick_best_audio(formats)
            if not audio_fmt:
                raise DownloadError("Не нашлось аудиодорожки для этого видео.")
            raw_path = os.path.join(TMP_DIR, f"{file_id}_audio.{audio_fmt.get('ext', 'm4a')}")
            await _direct_download(audio_fmt["url"], raw_path)
            out_path = os.path.join(TMP_DIR, f"{file_id}.mp3")
            await _run_ffmpeg(["-i", raw_path, "-vn", "-b:a", "192k", out_path])
            cleanup(raw_path)
            return out_path
        else:
            height = int(format_id)
            video_fmt, audio_fmt = _pick_video_audio(formats, height)
            if not video_fmt:
                raise DownloadError("Не нашлось подходящего видеоформата.")

            video_path = os.path.join(TMP_DIR, f"{file_id}_v.{video_fmt.get('ext', 'mp4')}")
            await _direct_download(video_fmt["url"], video_path)

            if audio_fmt and video_fmt.get("acodec") == "none":
                audio_path = os.path.join(TMP_DIR, f"{file_id}_a.{audio_fmt.get('ext', 'm4a')}")
                await _direct_download(audio_fmt["url"], audio_path)
                out_path = os.path.join(TMP_DIR, f"{file_id}.mp4")
                await _run_ffmpeg([
                    "-i", video_path, "-i", audio_path,
                    "-c", "copy", "-movflags", "+faststart", out_path,
                ])
                cleanup(video_path)
                cleanup(audio_path)
                return out_path
            else:
                # формат уже со звуком (muxed)
                out_path = os.path.join(TMP_DIR, f"{file_id}.mp4")
                await _run_ffmpeg(["-i", video_path, "-c", "copy", "-movflags", "+faststart", out_path])
                cleanup(video_path)
                return out_path

    except asyncio.TimeoutError:
        raise DownloadError("Скачивание заняло слишком много времени, попробуй другое качество или видео короче.")


def _pick_best_audio(formats: list[dict]) -> dict | None:
    audio_only = [f for f in formats if f.get("vcodec") == "none" and f.get("acodec") != "none" and f.get("url")]
    if not audio_only:
        return None
    return max(audio_only, key=lambda f: f.get("abr") or 0)


def _pick_video_audio(formats: list[dict], max_height: int) -> tuple[dict | None, dict | None]:
    # сначала пробуем muxed (видео+звук вместе) в нужной высоте — тогда аудио отдельно не нужно
    muxed = [
        f for f in formats
        if f.get("vcodec") != "none" and f.get("acodec") != "none"
        and f.get("height") and f["height"] <= max_height and f.get("url")
    ]
    if muxed:
        best_muxed = max(muxed, key=lambda f: f["height"])
        return best_muxed, None

    # иначе — раздельные видео (без звука) + лучшее аудио
    video_only = [
        f for f in formats
        if f.get("vcodec") != "none" and f.get("acodec") == "none"
        and f.get("height") and f["height"] <= max_height and f.get("url")
    ]
    if not video_only:
        return None, None
    best_video = max(video_only, key=lambda f: f["height"])
    return best_video, _pick_best_audio(formats)


async def _direct_download(url: str, dest_path: str):
    """Качает файл напрямую по прямой ссылке CDN, без прокси."""
    import aiohttp
    timeout = aiohttp.ClientTimeout(total=DOWNLOAD_TIMEOUT_SEC)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise DownloadError(f"Ошибка загрузки файла (код {resp.status}), попробуй ещё раз.")
            with open(dest_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(1024 * 1024):
                    f.write(chunk)


async def _run_ffmpeg(args: list[str]):
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", *args,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await asyncio.wait_for(proc.wait(), timeout=DOWNLOAD_TIMEOUT_SEC)
    if proc.returncode != 0:
        raise DownloadError("Не получилось обработать видео (ffmpeg), попробуй ещё раз.")


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
