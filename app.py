from fastapi import FastAPI
from assistant_backend_1.api.routers.telegram_router import router as telegram_router

app = FastAPI()

app.include_router(telegram_router)


@app.get("/")
async def root():
    return {"message": "AI Memory Assistant Backend Running"}
