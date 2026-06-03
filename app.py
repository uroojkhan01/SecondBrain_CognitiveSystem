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


@app.get("/")
async def root():
    return {"message": "AI Memory Assistant Backend Running"}
