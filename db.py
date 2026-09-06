import sqlite3
import json
from datetime import datetime, timezone
from contextlib import contextmanager

from config import DB_PATH


def init_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_seen TEXT NOT NULL,
                blocked INTEGER NOT NULL DEFAULT 0
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS pending_downloads (
                key TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                options_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                url TEXT NOT NULL,
                format TEXT NOT NULL,       -- e.g. "720p" or "mp3"
                file_size_mb REAL,
                status TEXT NOT NULL,       -- ok / error
                error_text TEXT,
                created_at TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS extra_credits (
                user_id INTEGER PRIMARY KEY,
                credits INTEGER NOT NULL DEFAULT 0  -- покупные скачивания сверх бесплатных
            )
        """)


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def register_user(user_id: int, username: str | None):
    """Вызывать при любом взаимодействии юзера с ботом (start, ссылка и т.п.)."""
    with _conn() as c:
        c.execute(
            "INSERT INTO users (user_id, username, first_seen, blocked) VALUES (?, ?, ?, 0)"
            " ON CONFLICT(user_id) DO UPDATE SET username = ?, blocked = 0",
            (user_id, username, datetime.now(timezone.utc).isoformat(), username),
        )


def mark_blocked(user_id: int, blocked: bool = True):
    with _conn() as c:
        c.execute("UPDATE users SET blocked = ? WHERE user_id = ?", (1 if blocked else 0, user_id))


def save_pending(key: str, user_id: int, url: str, options: list[dict]):
    """Сохраняем список форматов в БД, а не в память — переживает рестарт процесса."""
    with _conn() as c:
        c.execute(
            "INSERT INTO pending_downloads (key, user_id, url, options_json, created_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET url = ?, options_json = ?, created_at = ?",
            (key, user_id, url, json.dumps(options), datetime.now(timezone.utc).isoformat(),
             url, json.dumps(options), datetime.now(timezone.utc).isoformat()),
        )


def get_pending(key: str):
    """Возвращает (url, options) или (None, None), если не найдено."""
    with _conn() as c:
        row = c.execute(
            "SELECT url, options_json FROM pending_downloads WHERE key = ?", (key,)
        ).fetchone()
        if not row:
            return None, None
        return row[0], json.loads(row[1])


def delete_pending(key: str):
    with _conn() as c:
        c.execute("DELETE FROM pending_downloads WHERE key = ?", (key,))


def get_all_users():
    """Все юзера с количеством скачиваний и статусом блокировки."""
    with _conn() as c:
        return c.execute("""
            SELECT u.user_id, u.username, u.blocked, u.first_seen,
                   COUNT(d.id) FILTER (WHERE d.status = 'ok') as downloads_count
            FROM users u
            LEFT JOIN downloads d ON d.user_id = u.user_id
            GROUP BY u.user_id
            ORDER BY u.first_seen DESC
        """).fetchall()


def get_active_user_ids():
    """Для рассылки — только те, кто не заблокировал бота."""
    with _conn() as c:
        return [row[0] for row in c.execute("SELECT user_id FROM users WHERE blocked = 0").fetchall()]


def log_download(user_id: int, username: str, url: str, fmt: str,
                  file_size_mb: float | None, status: str, error_text: str = ""):
    with _conn() as c:
        c.execute(
            "INSERT INTO downloads (user_id, username, url, format, file_size_mb, status, error_text, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, username, url, fmt, file_size_mb, status, error_text,
             datetime.now(timezone.utc).isoformat()),
        )


def seconds_since_last_download(user_id: int) -> float | None:
    """None если скачиваний ещё не было."""
    with _conn() as c:
        row = c.execute(
            "SELECT created_at FROM downloads WHERE user_id = ? AND status = 'ok'"
            " ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        if not row:
            return None
        last = datetime.fromisoformat(row[0])
        return (datetime.now(timezone.utc) - last).total_seconds()


def count_downloads_today(user_id: int) -> int:
    """Успешные скачивания за текущие календарные сутки UTC."""
    today = datetime.now(timezone.utc).date().isoformat()
    with _conn() as c:
        row = c.execute(
            "SELECT COUNT(*) FROM downloads WHERE user_id = ? AND status = 'ok' AND created_at >= ?",
            (user_id, today),
        ).fetchone()
        return row[0] if row else 0


def get_extra_credits(user_id: int) -> int:
    with _conn() as c:
        row = c.execute("SELECT credits FROM extra_credits WHERE user_id = ?", (user_id,)).fetchone()
        return row[0] if row else 0


def add_extra_credits(user_id: int, amount: int):
    with _conn() as c:
        c.execute(
            "INSERT INTO extra_credits (user_id, credits) VALUES (?, ?)"
            " ON CONFLICT(user_id) DO UPDATE SET credits = credits + ?",
            (user_id, amount, amount),
        )


def spend_extra_credit(user_id: int):
    with _conn() as c:
        c.execute("UPDATE extra_credits SET credits = credits - 1 WHERE user_id = ?", (user_id,))


# --- для /admin и /logs ---

def get_stats():
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) FROM downloads WHERE status = 'ok'").fetchone()[0]
        today = datetime.now(timezone.utc).date().isoformat()
        today_count = c.execute(
            "SELECT COUNT(*) FROM downloads WHERE status = 'ok' AND created_at >= ?", (today,)
        ).fetchone()[0]
        top_users = c.execute(
            "SELECT user_id, username, COUNT(*) as cnt FROM downloads"
            " WHERE status = 'ok' GROUP BY user_id ORDER BY cnt DESC LIMIT 10"
        ).fetchall()
        return {"total": total, "today": today_count, "top_users": top_users}


def get_user_history(user_id: int, limit: int = 20):
    with _conn() as c:
        return c.execute(
            "SELECT url, format, file_size_mb, status, created_at FROM downloads"
            " WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
