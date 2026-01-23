"""
FastAPI приложение для AI-генератора постов для Telegram
"""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI

from app.api.endpoints import router
from app.config import settings
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


def setup_logging():
    """Настройка логирования в файл"""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    log_file = log_dir / "aibot.log"

    log_format = (
        "%(asctime)s - %(name)s - %(levelname)s - "
        "%(module)s:%(lineno)d - %(message)s"
    )
    date_format = "%Y-%m-%d %H:%M:%S"

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper()))

    root_logger.handlers.clear()

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(log_format, datefmt=date_format)
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(
        logging.DEBUG if settings.DEBUG else logging.INFO
    )
    console_handler.setFormatter(
        logging.Formatter(log_format, datefmt=date_format)
    )

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


@app.on_event("startup")
async def startup_event():
    """Инициализация при запуске приложения"""
    setup_logging()
    await init_db()


@app.get("/")
async def root():
    return {"message": "AI-генератор постов для Telegram API"}


@app.get("/health")
async def health_check():
    """Проверка работоспособности API"""
    return {"status": "ok"}
