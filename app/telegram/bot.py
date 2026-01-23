import logging

from telethon import TelegramClient

from app.config import settings

logger = logging.getLogger(__name__)


class TelegramBot:
    """
    Базовый класс для работы с Telegram
    """

    def __init__(self):
        """
        Инициализация бота

        Требует предварительной авторизации через authorize_telegram().
        """
        if not settings.TELEGRAM_API_ID or not settings.TELEGRAM_API_HASH:
            raise ValueError(
                "Не указаны TELEGRAM_API_ID и TELEGRAM_API_HASH. "
                "Установите их в переменных окружения."
            )

        session_name = getattr(
            settings, 'TELEGRAM_SESSION_NAME', 'telegram_session'
        )
        self.client = TelegramClient(
            session_name,
            settings.TELEGRAM_API_ID,
            settings.TELEGRAM_API_HASH
        )

    async def connect(self):
        """
        Подключиться к Telegram

        Требует предварительной авторизации через authorize_telegram().
        """
        if not self.client.is_connected():
            await self.client.start()
            logger.info("Подключено к Telegram")

    async def disconnect(self):
        """Отключиться от Telegram"""
        if self.client.is_connected():
            await self.client.disconnect()
            logger.info("Отключено от Telegram")
