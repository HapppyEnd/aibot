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

    # SberGigaChat (доступен в России!)))
    # Вариант 1: отдельные client_id и client_secret
    GIGACHAT_CLIENT_ID: Optional[str] = None
    GIGACHAT_CLIENT_SECRET: Optional[str] = None
    # Вариант 2: готовый base64 ключ (client_id:client_secret в base64)
    GIGACHAT_API_KEY: Optional[str] = None

    # App
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


settings = Settings()
