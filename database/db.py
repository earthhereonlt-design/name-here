```python
import aiosqlite
import asyncio
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/bot.db")

async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS checked_usernames (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                status TEXT NOT NULL,          -- 'available' | 'taken' | 'error'
                checked_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS available_usernames (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                found_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT NOT NULL,           -- 'INFO' | 'WARN' | 'ERROR'
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS stats (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        await db.commit()
    await _ensure_stats()

async def _ensure_stats():
    defaults = {
        "total_checked": "0",
        "total_available": "0",
        "total_errors": "0",
        "total_rate_limits": "0",
        "start_time": "",
        "current_username": "",
    }
    async with aiosqlite.connect(DB_PATH) as db:
        for key, val in defaults.items():
            await db.execute(
                "INSERT OR IGNORE INTO stats (key, value) VALUES (?, ?)", (key, val)
            )
        await db.commit()

# ── Stats ──────────────────────────────────────────────────────────────

async def get_stat(key: str) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM stats WHERE key=?", (key,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else ""

async def set_stat(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO stats (key, value) VALUES (?, ?)", (key, value)
        )
        await db.commit()

async def increment_stat(key: str, by: int = 1):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE stats SET value = CAST(CAST(value AS INTEGER) + ? AS TEXT) WHERE key=?",
            (by, key),
        )
        await db.commit()

# ── Usernames ──────────────────────────────────────────────────────────

async def is_checked(username: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM checked_usernames WHERE username=?", (username,)
        ) as cur:
            return await cur.fetchone() is not None

async def record_check(username: str, status: str):
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO checked_usernames (username, status, checked_at) VALUES (?, ?, ?)",
            (username, status, now),
        )
        await db.commit()

async def record_available(username: str):
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO available_usernames (username, found_at) VALUES (?, ?)",
            (username, now),
        )
        await db.commit()

async def get_all_available() -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT username FROM available_usernames ORDER BY found_at"
        ) as cur:
            rows = await cur.fetchall()
            return [r[0] for r in rows]

# ── Logs ───────────────────────────────────────────────────────────────

async def add_log(level: str, message: str):
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO logs (level, message, created_at) VALUES (?, ?, ?)",
            (level, message, now),
        )
        # keep only last 500 logs
        await db.execute(
            "DELETE FROM logs WHERE id NOT IN (SELECT id FROM logs ORDER BY id DESC LIMIT 500)"
        )
        await db.commit()

async def get_last_logs(n: int = 5) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT level, message, created_at FROM logs ORDER BY id DESC LIMIT ?", (n,)
        ) as cur:
            rows = await cur.fetchall()
            return [{"level": r[0], "msg": r[1], "at": r[2]} for r in reversed(rows)]

# ── Bot state (running flag persistence) ──────────────────────────────

async def set_state(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)", (key, value)
        )
        await db.commit()

async def get_state(key: str, default: str = "") -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM bot_state WHERE key=?", (key,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else default

# ── Clear ──────────────────────────────────────────────────────────────

async def clear_all():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            DELETE FROM logs;
            DELETE FROM stats;
        """)
        await db.commit()
    await _ensure_stats()
```

---
