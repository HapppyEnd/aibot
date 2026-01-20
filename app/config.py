"""
Конфигурация приложения
"""
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Настройки приложения"""

    # Database
    DATABASE_URL: str = "sqlite:///./aibot.db"

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # Telegram (опционально для тестирования)
    TELEGRAM_API_ID: Optional[int] = None
    TELEGRAM_API_HASH: Optional[str] = None
    TELEGRAM_CHANNEL_USERNAME: Optional[str] = None

    # OpenAI (опционально для тестирования)
    OPENAI_API_KEY: Optional[str] = None

    # App
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
