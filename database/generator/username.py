```python
import os
import json
import asyncio
import httpx
from bot.database import db
from bot.utils.helpers import log

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL   = os.getenv("OPENROUTER_MODEL", "mistralai/mistral-7b-instruct")
OPENROUTER_URL     = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """You are a creative username generator. Your only job is to generate Instagram usernames.
Rules:
- Bases ONLY: adi, aadi (and close variants like ad, aad)
- Separators: . or _ (use sparingly, not always)
- Lowercase only
- Tech / dev / startup aesthetic
- Short and clean (4–10 chars total)
- Suffixes allowed: .js .py .io .sh .xp .go .rs .ts .dev .ui .ux .ai .co .core .app .run .lab
- Sometimes 2-letter suffixes
- No cringe, no numbers, no underscores back-to-back
- No duplicates within the batch
Return ONLY a JSON array of exactly 25 strings. No explanation. No markdown."""

USER_PROMPT = """Generate 25 unique Instagram-style usernames using the bases: adi, aadi (and variants ad, aad).
Already used (skip these): {used}
Return ONLY a valid JSON array."""

async def generate_usernames(used: set[str]) -> list[str]:
    """Call OpenRouter and return 25 fresh usernames."""
    used_sample = list(used)[-60:] if len(used) > 60 else list(used)
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": USER_PROMPT.format(used=used_sample)},
        ],
        "temperature": 0.95,
        "max_tokens": 400,
    }
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/username-bot",
        "X-Title": "Instagram Username Finder",
    }

    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(OPENROUTER_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                raw = data["choices"][0]["message"]["content"].strip()
                # strip markdown fences if model adds them
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                usernames: list[str] = json.loads(raw)
                # sanitise
                clean = [
                    u.lower().strip()
                    for u in usernames
                    if isinstance(u, str) and 3 <= len(u.strip()) <= 30
                ]
                await log("INFO", f"Generated {len(clean)} usernames from AI")
                return clean[:25]
        except Exception as e:
            await log("WARN", f"Generator attempt {attempt} failed: {e}")
            await asyncio.sleep(3 * attempt)

    await log("ERROR", "All generator attempts failed; returning empty list")
    return []
```

---
