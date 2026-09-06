import os

# --- Telegram ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]

LOCAL_BOT_API_URL = os.getenv("LOCAL_BOT_API_URL", "")

# --- Скачивание ---
MAX_QUALITY = "1080"
TMP_DIR = "/tmp/ytbot"
DOWNLOAD_TIMEOUT_SEC = 600

# --- Прокси ---
PROXY_URL = os.getenv("PROXY_URL", "")

# --- Лимиты и монетизация ---
FREE_DOWNLOADS_PER_DAY = 5
STARS_PRICE_PER_EXTRA_BATCH = 100
EXTRA_BATCH_SIZE = 5
COOLDOWN_SECONDS = 600

# --- Мониторинг ошибок ---
ERROR_RATE_CHECK_INTERVAL_SEC = 300
ERROR_RATE_THRESHOLD_PERCENT = 30
ERROR_RATE_MIN_SAMPLE = 5
ERROR_RATE_ALERT_COOLDOWN_SEC = 1800

# --- БД ---
DB_PATH = os.getenv("DB_PATH", "ytbot.db")
