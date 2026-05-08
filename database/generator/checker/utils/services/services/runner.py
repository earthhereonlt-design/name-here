```python
import asyncio
import os
import time
from aiogram import Bot
from bot.checker.instagram import InstagramChecker
from bot.generator.username import generate_usernames
from bot.database import db
from bot.utils.helpers import log, random_delay, format_duration

RATE_LIMIT_COOLDOWN = int(os.getenv("RATE_LIMIT_COOLDOWN", "60"))   # seconds
BATCH_DELAY        = float(os.getenv("BATCH_DELAY", "3.0"))         # between batches
CHECK_DELAY_MIN    = float(os.getenv("CHECK_DELAY_MIN", "2.5"))
CHECK_DELAY_MAX    = float(os.getenv("CHECK_DELAY_MAX", "5.0"))


class BotRunner:
    """Manages the infinite generate→check loop."""

    def __init__(self, bot: Bot, chat_id: int):
        self.bot      = bot
        self.chat_id  = chat_id
        self._running = False
        self._task: asyncio.Task | None = None
        self._checker = InstagramChecker()
        self._progress_msg_id: int | None = None
        self._used: set[str] = set()  # in-memory seen set for this session

    # ── Public API ──────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self):
        if self._running:
            return
        self._running = True
        await db.set_state("running", "1")
        await db.set_stat("start_time", str(time.time()))
        await log("INFO", "Runner started")
        await self._checker.start()
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        if not self._running:
            return
        self._running = False
        await db.set_state("running", "0")
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._checker.stop()
        await log("INFO", "Runner stopped")

    # ── Core loop ───────────────────────────────────────────────────────

    async def _loop(self):
        # Load already-checked usernames to avoid repeats across restarts
        async with __import__("aiosqlite").connect("data/bot.db") as db_conn:
            async with db_conn.execute("SELECT username FROM checked_usernames") as cur:
                rows = await cur.fetchall()
                self._used = {r[0] for r in rows}

        while self._running:
            try:
                # Generate batch
                await log("INFO", "Requesting new batch from AI...")
                batch = await generate_usernames(self._used)
                if not batch:
                    await log("WARN", "Empty batch, retrying in 10s")
                    await asyncio.sleep(10)
                    continue

                for username in batch:
                    if not self._running:
                        break
                    if username in self._used:
                        continue

                    self._used.add(username)
                    await db.set_stat("current_username", username)
                    await self._update_progress()

                    result = await self._checker.check(username)

                    if result == "available":
                        await db.record_check(username, "available")
                        await db.record_available(username)
                        await db.increment_stat("total_checked")
                        await db.increment_stat("total_available")
                        await log("INFO", f"AVAILABLE: {username}")
                        await self._notify_available(username)

                    elif result == "taken":
                        await db.record_check(username, "taken")
                        await db.increment_stat("total_checked")

                    elif result == "rate_limit":
                        await db.increment_stat("total_rate_limits")
                        await log("WARN", f"Rate limited. Cooling down {RATE_LIMIT_COOLDOWN}s")
                        await self._send_cooldown_notice()
                        await asyncio.sleep(RATE_LIMIT_COOLDOWN)

                    elif result == "error":
                        await db.record_check(username, "error")
                        await db.increment_stat("total_errors")
                        await log("WARN", f"Error checking {username}")

                    await random_delay(CHECK_DELAY_MIN, CHECK_DELAY_MAX)

                await asyncio.sleep(BATCH_DELAY)

            except asyncio.CancelledError:
                break
            except Exception as e:
                await log("ERROR", f"Loop error: {e}")
                await asyncio.sleep(15)  # auto-recovery pause

    # ── Telegram messaging ──────────────────────────────────────────────

    async def _update_progress(self):
        checked  = await db.get_stat("total_checked")
        avail    = await db.get_stat("total_available")
        errors   = await db.get_stat("total_errors")
        rl       = await db.get_stat("total_rate_limits")
        cur      = await db.get_stat("current_username")
        start_ts = await db.get_stat("start_time")
        runtime  = format_duration(time.time() - float(start_ts)) if start_ts else "—"

        text = (
            "🔄 *Username Finder Running*\n\n"
            f"🔍 Checking: `{cur}`\n"
            f"✅ Checked: `{checked}`\n"
            f"🟢 Available: `{avail}`\n"
            f"❌ Errors: `{errors}`\n"
            f"⏳ Rate limits: `{rl}`\n"
            f"🕐 Runtime: `{runtime}`"
        )
        try:
            if self._progress_msg_id:
                await self.bot.edit_message_text(
                    text=text,
                    chat_id=self.chat_id,
                    message_id=self._progress_msg_id,
                    parse_mode="Markdown",
                )
            else:
                msg = await self.bot.send_message(
                    self.chat_id, text, parse_mode="Markdown"
                )
                self._progress_msg_id = msg.message_id
        except Exception:
            pass  # silently ignore Telegram edit errors (rate limits, etc.)

    async def _notify_available(self, username: str):
        text = f"🟢 *AVAILABLE USERNAME*\n\n`{username}`"
        await self.bot.send_message(self.chat_id, text, parse_mode="Markdown")

    async def _send_cooldown_notice(self):
        try:
            await self.bot.send_message(
                self.chat_id,
                f"⚠️ Rate limited by Instagram. Cooling down for {RATE_LIMIT_COOLDOWN}s...",
            )
        except Exception:
            pass
```

---
