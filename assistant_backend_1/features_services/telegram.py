import os
import httpx
from assistant_backend_1.config import TELEGRAM_BOT_TOKEN


async def send_message(chat_id: int, text: str):
    # ✅ This fetches the token fresh on every single request
    token = os.getenv("TELEGRAM_BOT_TOKEN") or TELEGRAM_BOT_TOKEN
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": text
    }

    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload)
