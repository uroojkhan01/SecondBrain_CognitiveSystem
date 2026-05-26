from fastapi import APIRouter, Request
from assistant_backend_1.api.handlers.telegram_handler import telegram_webhook,notion_oauth_callback

router = APIRouter()

router.post("/webhook/telegram")(telegram_webhook)
router.get("/notion/callback")(notion_oauth_callback)