from fastapi import APIRouter, Request
from SecondBrain_CognitiveSystem.assistant_backend_1.helpers import load_users
from assistant_backend_1.api.handlers.telegram_handler import telegram_webhook,notion_oauth_callback

#remove this function when switching to a real database, it's just for debugging purposes to see the users saved in the JSON file
async def debug_users():  
    return load_users()

router = APIRouter()
router.post("/webhook/telegram")(telegram_webhook)
router.get("/notion/callback")(notion_oauth_callback)
#remove this endpoint when switching to a real database, it's just for debugging purposes to see the users saved in the JSON file
router.get("/debug/users")(debug_users)

