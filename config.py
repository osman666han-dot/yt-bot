import os

# --- Telegram ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]

# Локальный Bot API сервер (для лимита 2 ГБ вместо 50 МБ)
# Поднимается отдельным сервисом telegram-bot-api в Railway
LOCAL_BOT_API_URL = os.getenv("LOCAL_BOT_API_URL", "")  # напр. http://telegram-bot-api:8081

# --- Скачивание ---
MAX_QUALITY = "1080"  # максимальное качество видео, выше не отдаём
TMP_DIR = "/tmp/ytbot"  # временная папка в контейнере, не volume
DOWNLOAD_TIMEOUT_SEC = 600  # таймаут на одно скачивание

# --- Прокси (пока выключено, включаем одной переменной когда нужно) ---
PROXY_URL = os.getenv("PROXY_URL", "")  # напр. socks5://user:pass@host:port, пусто = без прокси

# --- Лимиты и монетизация ---
FREE_DOWNLOADS_PER_DAY = 5
STARS_PRICE_PER_EXTRA_BATCH = 100  # звёзд за каждые +5 скачиваний сверх бесплатных
EXTRA_BATCH_SIZE = 5
COOLDOWN_SECONDS = 600  # не чаще 1 скачивания раз в 10 минут на юзера

# --- БД ---
DB_PATH = os.getenv("DB_PATH", "ytbot.db")  # локальный файл, для логов не нужен volume с большим объёмом
