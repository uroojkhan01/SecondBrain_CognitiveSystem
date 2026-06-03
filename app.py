from fastapi import FastAPI
from contextlib import asynccontextmanager
from assistant_backend_1.api.routers.telegram_router import router as telegram_router
from assistant_backend_1.features_services.reminders import start_reminder_scheduler
import threading


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start reminder scheduler in background thread
    thread = threading.Thread(target=start_reminder_scheduler, daemon=True)
    thread.start()
    print("✅ Reminder scheduler running in background")
    yield


app = FastAPI()
app.include_router(telegram_router)


@app.get("/")
async def root():
    return {"message": "AI Memory Assistant Backend Running"}
