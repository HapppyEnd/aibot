"""
Публикация постов в Telegram-канал через Telethon
"""
import logging
from typing import Optional

from telethon import TelegramClient
from telethon.errors import ChannelInvalidError, UsernameInvalidError

from app.config import settings

logger = logging.getLogger(__name__)


class TelegramPublisher:
    """Класс для публикации постов в Telegram-канал"""

    def __init__(
        self,
        api_id: Optional[int] = None,
        api_hash: Optional[str] = None,
        channel_username: Optional[str] = None
    ):
        """
        Инициализация публикатора

        Args:
            api_id: API ID из my.telegram.org
            api_hash: API Hash из my.telegram.org
            channel_username: Username канала (без @) или ID канала
        """
        self.api_id = api_id or settings.TELEGRAM_API_ID
        self.api_hash = api_hash or settings.TELEGRAM_API_HASH
        self.channel_username = (
            channel_username or settings.TELEGRAM_CHANNEL_USERNAME
        )

        if not self.api_id or not self.api_hash:
            raise ValueError(
                "Не указаны TELEGRAM_API_ID и TELEGRAM_API_HASH. "
                "Установите их в переменных окружения или передайте напрямую."
            )

        if not self.channel_username:
            raise ValueError(
                "Не указан TELEGRAM_CHANNEL_USERNAME. "
                "Установите его в переменных окружения или передайте напрямую."
            )

        self.client = TelegramClient(
            'telegram_publisher_session',
            self.api_id,
            self.api_hash
        )

    async def connect(self):
        """Подключиться к Telegram"""
        if not self.client.is_connected():
            await self.client.start()
            logger.info("Подключено к Telegram")

    async def disconnect(self):
        """Отключиться от Telegram"""
        if self.client.is_connected():
            await self.client.disconnect()
            logger.info("Отключено от Telegram")

    async def publish_post(
        self,
        text: str,
        channel_username: Optional[str] = None
    ) -> Optional[int]:
        """
        Опубликовать пост в канал

        Args:
            text: Текст поста для публикации
            channel_username: Username канала
                (если не указан при инициализации)

        Returns:
            ID сообщения или None при ошибке
        """
        try:
            await self.connect()

            channel = channel_username or self.channel_username
            # Убираем @ если есть
            channel = channel.lstrip('@')

            logger.info(f"Публикация поста в канал: {channel}")

            # Отправляем сообщение
            message = await self.client.send_message(channel, text)
            message_id = message.id

            logger.info(
                f"Пост успешно опубликован! ID сообщения: {message_id}"
            )
            return message_id

        except (ChannelInvalidError, UsernameInvalidError) as e:
            logger.error(
                f"Ошибка: канал '{channel}' не найден "
                f"или недоступен: {e}"
            )
            return None
        except Exception as e:
            logger.error(f"Ошибка при публикации поста: {e}", exc_info=True)
            return None

    async def test_connection(self) -> bool:
        """
        Проверить подключение к Telegram и доступ к каналу

        Returns:
            True если все работает, False в противном случае
        """
        try:
            await self.connect()
            channel = self.channel_username.lstrip('@')

            # Пытаемся получить информацию о канале
            entity = await self.client.get_entity(channel)
            logger.info(f"Канал найден: {entity.title}")
            return True

        except (ChannelInvalidError, UsernameInvalidError) as e:
            logger.error(f"Канал '{channel}' недоступен: {e}")
            return False
        except Exception as e:
            logger.error(f"Ошибка при проверке канала: {e}", exc_info=True)
            return False
