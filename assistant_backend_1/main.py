from fastapi import FastAPI
from assistant_backend_1.api.routers.telegram_router import router

app = FastAPI()

app.include_router(router)