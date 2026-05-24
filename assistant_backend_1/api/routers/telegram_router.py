from fastapi import APIRouter, Request
from assistant_backend_1.api.handlers.telegram_handler import telegram_webhook

router = APIRouter()

router.post("/webhook/telegram")(telegram_webhook)
