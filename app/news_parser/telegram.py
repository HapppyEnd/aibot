"""
Парсер новостей из Telegram-каналов
"""
import asyncio
import logging
from datetime import datetime

from telethon import TelegramClient
from telethon.errors import (ChannelInvalidError, ChannelPrivateError,
                             UsernameInvalidError)
from telethon.tl.types import Message, MessageMediaDocument, MessageMediaPhoto

from app.config import settings

logger = logging.getLogger(__name__)

# Константы
MIN_TEXT_LENGTH = 5  # Минимальная длина текста сообщения для обработки
MAX_TITLE_LENGTH = 100  # Максимальная длина заголовка
TELEGRAM_URL_TEMPLATE = "https://t.me/{channel}/{message_id}"
MEDIA_PHOTO_LABEL = "[Фото]"
MEDIA_DOCUMENT_LABEL = "[Документ]"
DEFAULT_PARSE_LIMIT = 100  # Количество сообщений по умолчанию


class TelegramChannelParser:
    """
    Парсер для получения новостей из публичных Telegram-каналов

    Примеры использования:

    # Парсинг канала по username
    parser = TelegramChannelParser(
        api_id=12345,
        api_hash='your_api_hash',
        channel_username='channel_name'
    )
    news = parser.parse()

    # Парсинг последних N сообщений
    news = parser.parse(limit=50)
    """

    def __init__(
        self,
        channel_username: str,
        api_id: int | None = None,
        api_hash: str | None = None
    ):
        """
        Инициализация парсера Telegram-канала

        Args:
            channel_username: Username канала (без @) или ID канала
            api_id: API ID из my.telegram.org
                (если не указан, берется из настроек)
            api_hash: API Hash из my.telegram.org
                (если не указан, берется из настроек)
        """
        self.channel_username = channel_username.lstrip('@')
        self.api_id = api_id or settings.TELEGRAM_API_ID
        self.api_hash = api_hash or settings.TELEGRAM_API_HASH

        if not self.api_id or not self.api_hash:
            raise ValueError(
                "Не указаны TELEGRAM_API_ID и TELEGRAM_API_HASH. "
                "Установите их в переменных окружения или передайте напрямую."
            )

        self.client = TelegramClient(
            'telegram_parser_session',
            self.api_id,
            self.api_hash
        )

    async def _connect(self):
        if not self.client.is_connected():
            await self.client.start()
            logger.info("Подключено к Telegram")

    async def _disconnect(self):
        if self.client.is_connected():
            await self.client.disconnect()
            logger.info("Отключено от Telegram")

    def _extract_text(self, message: Message) -> str:
        """
        Извлекает текст из сообщения

        Args:
            message: Объект сообщения из Telethon

        Returns:
            Текст сообщения
        """
        text = message.message or ''

        if message.media:
            if isinstance(message.media, MessageMediaPhoto):
                media_label = f'\n📷 {MEDIA_PHOTO_LABEL}'
                text += media_label if text else MEDIA_PHOTO_LABEL
            elif isinstance(message.media, MessageMediaDocument):
                media_label = f'\n📎 {MEDIA_DOCUMENT_LABEL}'
                text += media_label if text else MEDIA_DOCUMENT_LABEL

        return text.strip()

    def _extract_url(
        self, message: Message, channel_username: str
    ) -> str | None:
        """
        Формирует URL сообщения в канале

        Args:
            message: Объект сообщения из Telethon
            channel_username: Username канала

        Returns:
            URL сообщения или None
        """
        if message.id:
            return TELEGRAM_URL_TEMPLATE.format(
                channel=channel_username,
                message_id=message.id
            )
        return None

    def _parse_message(
        self, message: Message, channel_username: str
    ) -> dict | None:
        """
        Преобразует сообщение Telegram в формат новости

        Args:
            message: Объект сообщения из Telethon
            channel_username: Username канала

        Returns:
            Словарь с данными новости или None
        """
        try:
            text = self._extract_text(message)

            if not text or len(text) < MIN_TEXT_LENGTH:
                return None

            text_length = len(text)
            if text_length > MAX_TITLE_LENGTH:
                title = text[:MAX_TITLE_LENGTH] + '...'
            else:
                title = text
            title = title.split('\n')[0].strip()

            if text_length > MAX_TITLE_LENGTH:
                summary = text[MAX_TITLE_LENGTH:].strip()
            else:
                summary = ''

            url = self._extract_url(message, channel_username)

            published_at = message.date
            if published_at and published_at.tzinfo:
                published_at = published_at.replace(tzinfo=None)

            return {
                'title': title,
                'url': url,
                'summary': summary,
                'source': channel_username,
                'published_at': published_at or datetime.now(),
                'raw_text': text
            }
        except Exception as e:
            logger.warning(
                f"Ошибка при обработке сообщения {message.id}: {e}",
                exc_info=True
            )
            return None

    async def _parse_async(
        self, limit: int = DEFAULT_PARSE_LIMIT
    ) -> list[dict]:
        """
        Асинхронный парсинг сообщений из канала

        Args:
            limit: Максимальное количество сообщений для парсинга

        Returns:
            Список словарей с новостями
        """
        await self._connect()

        try:
            entity = await self.client.get_entity(self.channel_username)
            logger.info(
                f"Парсинг канала: {entity.title} "
                f"(@{self.channel_username})"
            )

            result = []
            async for message in self.client.iter_messages(
                entity,
                limit=limit
            ):
                if not isinstance(message, Message):
                    continue

                news_item = self._parse_message(message, self.channel_username)
                if news_item:
                    result.append(news_item)

            logger.info(
                f"Парсер Telegram канала "
                f"'{self.channel_username}' собрал {len(result)} новостей"
            )
            return result

        except (ChannelInvalidError, UsernameInvalidError) as e:
            logger.error(
                f"Канал '{self.channel_username}' не найден: {e}"
            )
            return []
        except ChannelPrivateError as e:
            logger.error(
                f"Канал '{self.channel_username}' приватный: {e}"
            )
            return []
        except Exception as e:
            logger.error(
                f"Ошибка при парсинге канала '{self.channel_username}': {e}",
                exc_info=True
            )
            return []
        finally:
            await self._disconnect()

    def parse(self, limit: int = DEFAULT_PARSE_LIMIT) -> list[dict]:
        """
        Парсит сообщения из Telegram-канала

        Args:
            limit: Максимальное количество сообщений для парсинга

        Returns:
            Список словарей с новостями:
            {
                'title': str,
                'url': str,
                'summary': str,
                'source': str,
                'published_at': datetime,
                'raw_text': str
            }
        """
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(self._parse_async(limit))
