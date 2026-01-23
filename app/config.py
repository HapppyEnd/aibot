"""
Конфигурация приложения
"""
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Настройки приложения (загружаются из .env файла)"""

    # Database
    DATABASE_URL: str

    # Celery
    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str

    # Telegram
    TELEGRAM_API_ID: Optional[int] = None
    TELEGRAM_API_HASH: Optional[str] = None
    TELEGRAM_CHANNEL_USERNAME: Optional[str] = None
    TELEGRAM_SESSION_NAME: Optional[str] = 'telegram_session'

    # SberGigaChat (доступен в России!)))
    # отдельные client_id и client_secret
    GIGACHAT_CLIENT_ID: Optional[str] = None
    GIGACHAT_CLIENT_SECRET: Optional[str] = None
    # готовый base64 ключ
    GIGACHAT_API_KEY: Optional[str] = None

    # App
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


settings = Settings()
