from fastapi import FastAPI
from contextlib import asynccontextmanager
from assistant_backend_1.api.routers.telegram_router import router as telegram_router
from assistant_backend_1.features_services.reminders import start_reminder_scheduler
import threading


@asynccontextmanager
async def lifespan(app: FastAPI):
    thread = threading.Thread(target=start_reminder_scheduler, daemon=True)

    try:
        thread.start()
        print("Scheduler started")
    except Exception as e:
        print("Scheduler failed:", e)

    yield


app = FastAPI(lifespan=lifespan)
app.include_router(telegram_router)

from pydantic import BaseModel
import assistant_backend_1.config as config

class ToggleLLMRequest(BaseModel):
    enable: bool

@app.post("/toggle-llm")
async def toggle_llm(request: ToggleLLMRequest):
    config.ENABLE_LLM_API = request.enable
    status = "enabled" if config.ENABLE_LLM_API else "disabled"
    return {"message": f"LLM API has been {status}"}

@app.get("/")
async def root():
    return {"message": "AI Memory Assistant Backend Running", "llm_enabled": config.ENABLE_LLM_API}
