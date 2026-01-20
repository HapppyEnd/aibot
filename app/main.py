"""
FastAPI приложение для AI-генератора постов для Telegram
"""
from fastapi import FastAPI

from app.api.endpoints import router
from app.database import init_db

app = FastAPI(
    title="AI-генератор постов для Telegram",
    description=(
        "Сервис для автоматической генерации и публикации "
        "постов в Telegram-канал"
    ),
    version="1.0.0"
)

app.include_router(router, prefix="/api", tags=["api"])


@app.on_event("startup")
async def startup_event():
    """Инициализация БД при запуске приложения"""
    init_db()


@app.get("/")
async def root():
    return {"message": "AI-генератор постов для Telegram API"}


@app.get("/health")
async def health_check():
    """Проверка работоспособности API"""
    return {"status": "ok"}
