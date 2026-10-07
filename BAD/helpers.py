import aiohttp

BATBIN_URL = "https://batbin.me/"
MAX_PASTE_CHARS = 300_000  # keep the newest part if a log is huge


async def batbin(text: str):
    """Upload text to batbin.me and return the link (None if it fails)."""
    if not text:
        return None
    text = text[-MAX_PASTE_CHARS:]
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{BATBIN_URL}api/v2/paste",
                data=text.encode(),
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    return None
        if isinstance(data, dict) and data.get("success"):
            return BATBIN_URL + data["message"]
    except Exception:
        pass
    return None
