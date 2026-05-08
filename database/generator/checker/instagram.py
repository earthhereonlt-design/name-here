```python
import asyncio
import random
import httpx
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from bot.utils.helpers import log, random_delay, random_user_agent

INSTAGRAM_URL = "https://www.instagram.com/{username}/"
NOT_FOUND_INDICATORS = [
    "Sorry, this page isn't available",
    "The link you followed may be broken",
    '"pageType":"profileNotFound"',
    '"pageNotFound":true',
]

# ── Lightweight HTTP check ─────────────────────────────────────────────

async def _http_check(username: str, client: httpx.AsyncClient) -> str | None:
    """
    Returns 'available', 'taken', or None (inconclusive → use Playwright).
    """
    url = INSTAGRAM_URL.format(username=username)
    headers = {
        "User-Agent": random_user_agent(),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.google.com/",
    }
    try:
        resp = await client.get(url, headers=headers, follow_redirects=True, timeout=15)
        if resp.status_code == 404:
            return "available"
        if resp.status_code == 429:
            return "rate_limit"
        if resp.status_code == 200:
            text = resp.text
            if any(ind in text for ind in NOT_FOUND_INDICATORS):
                return "available"
            # likely taken or login wall
            if "login" in resp.url.path or "accounts/login" in str(resp.url):
                return None  # inconclusive, try Playwright
            return "taken"
        return None  # inconclusive
    except httpx.TimeoutException:
        return "timeout"
    except Exception:
        return None


# ── Playwright manager ─────────────────────────────────────────────────

class PlaywrightChecker:
    def __init__(self):
        self._pw = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    async def start(self):
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--single-process",
            ],
        )
        self._context = await self._browser.new_context(
            user_agent=random_user_agent(),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            timezone_id="America/New_York",
        )
        await log("INFO", "Playwright browser started")

    async def stop(self):
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()
        except Exception as e:
            await log("WARN", f"Playwright cleanup warning: {e}")
        await log("INFO", "Playwright browser stopped")

    async def check(self, username: str) -> str:
        """Returns 'available', 'taken', 'error', or 'rate_limit'."""
        if not self._context:
            return "error"
        page: Page | None = None
        try:
            page = await self._context.new_page()
            await page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2}", lambda r: r.abort())
            url = INSTAGRAM_URL.format(username=username)
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=20_000)

            if resp and resp.status == 404:
                return "available"
            if resp and resp.status == 429:
                return "rate_limit"

            content = await page.content()
            if any(ind in content for ind in NOT_FOUND_INDICATORS):
                return "available"

            final_url = page.url
            if "accounts/login" in final_url:
                # redirected to login → username doesn't exist (Instagram quirk)
                # BUT sometimes it's a rate limit redirect; check content
                if "rate" in content.lower() or "try again" in content.lower():
                    return "rate_limit"
                return "available"

            return "taken"
        except Exception as e:
            await log("WARN", f"Playwright check error for {username}: {e}")
            return "error"
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass


# ── Combined checker ───────────────────────────────────────────────────

class InstagramChecker:
    def __init__(self):
        self._pw = PlaywrightChecker()
        self._http_client: httpx.AsyncClient | None = None
        self._sem = asyncio.Semaphore(1)  # one check at a time to avoid bans

    async def start(self):
        self._http_client = httpx.AsyncClient(
            headers={"User-Agent": random_user_agent()},
            follow_redirects=True,
        )
        await self._pw.start()

    async def stop(self):
        await self._pw.stop()
        if self._http_client:
            await self._http_client.aclose()

    async def check(self, username: str) -> str:
        """
        Returns 'available', 'taken', 'error', or 'rate_limit'.
        Tries HTTP first, falls back to Playwright if inconclusive.
        """
        async with self._sem:
            # 1. HTTP check
            result = await _http_check(username, self._http_client)
            if result in ("available", "taken", "rate_limit"):
                return result

            # 2. Playwright fallback
            await log("INFO", f"HTTP inconclusive for {username}, using Playwright")
            await random_delay(1.5, 3.0)
            return await self._pw.check(username)
```

---
