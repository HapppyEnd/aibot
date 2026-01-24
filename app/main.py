import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI

from app.api.endpoints import router
from app.config import settings
from app.database import init_db


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


@asynccontextmanager
async def lifespan(app: FastAPI):

    setup_logging()
    await init_db()

    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.models import Source

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Source).filter(Source.enabled.is_(True))
        )
        enabled = result.scalars().all()
        sources_count = len(enabled)
        if sources_count > 0:
            from app.tasks import parse_all_sources, process_news_items
            parse_all_sources.delay()
            process_news_items.delay()

    yield


app = FastAPI(
    title="AI-генератор постов для Telegram",
    description=(
        "Сервис для автоматической генерации и публикации "
        "постов в Telegram-канал"
    ),
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(router, prefix="/api", tags=["api"])


@app.get("/")
async def root():
    return {"message": "AI-генератор постов для Telegram API"}


@app.get("/health")
async def health_check():
    """Проверка работоспособности API"""
    return {"status": "ok"}
