"""
Конфигурация приложения
"""

from urllib.parse import quote_plus

from pydantic import computed_field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Настройки приложения (загружаются из .env файла)"""

    # Database
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "aibot"

    @computed_field
    @property
    def DATABASE_URL(self) -> str:
        pw = quote_plus(self.POSTGRES_PASSWORD)
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{pw}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # Celery
    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str

    # Telegram
    TELEGRAM_API_ID: int | None = None
    TELEGRAM_API_HASH: str | None = None
    TELEGRAM_CHANNEL_USERNAME: str | None = None
    TELEGRAM_SESSION_NAME: str | None = 'telegram_session'

    # SberGigaChat (доступен в России!)))
    # отдельные client_id и client_secret
    GIGACHAT_CLIENT_ID: str | None = None
    GIGACHAT_CLIENT_SECRET: str | None = None
    # готовый base64 ключ
    GIGACHAT_API_KEY: str | None = None

    # App
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


settings = Settings()
