import logging
from datetime import datetime

from telethon import TelegramClient
from telethon.errors import (ChannelInvalidError, ChannelPrivateError,
                             UsernameInvalidError)
from telethon.tl.types import Message, MessageMediaDocument, MessageMediaPhoto

from app.config import settings

logger = logging.getLogger(__name__)

MIN_TEXT_LENGTH = 5
MAX_TITLE_LENGTH = 100
TELEGRAM_URL_TEMPLATE = "https://t.me/{channel}/{message_id}"
MEDIA_PHOTO_LABEL = "[Фото]"
MEDIA_DOCUMENT_LABEL = "[Документ]"
DEFAULT_PARSE_LIMIT = 100


class TelegramChannelParser:
    """Парсер новостей из публичных Telegram-каналов."""

    def __init__(
        self,
        channel_username: str,
        api_id: int | None = None,
        api_hash: str | None = None
    ):
        self.channel_username = channel_username.lstrip('@')
        self.api_id = api_id or settings.TELEGRAM_API_ID
        self.api_hash = api_hash or settings.TELEGRAM_API_HASH

        if not self.api_id or not self.api_hash:
            raise ValueError(
                "Не указаны TELEGRAM_API_ID и TELEGRAM_API_HASH. ")

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
        """Извлекает текст из сообщения."""
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
        """Формирует URL сообщения в канале."""
        if message.id:
            return TELEGRAM_URL_TEMPLATE.format(
                channel=channel_username,
                message_id=message.id
            )
        return None

    def _parse_message(
        self, message: Message, channel_username: str
    ) -> dict | None:
        """Преобразует сообщение Telegram в формат новости."""
        try:
            text = self._extract_text(message)
            if not text or len(text) < MIN_TEXT_LENGTH:
                return None

            title = (
                text[:MAX_TITLE_LENGTH] + '...'
                if len(text) > MAX_TITLE_LENGTH else text
            )
            title = title.split('\n')[0].strip()
            summary = (
                text[MAX_TITLE_LENGTH:].strip()
                if len(text) > MAX_TITLE_LENGTH else ''
            )

            if message.date and message.date.tzinfo:
                published_at = message.date.replace(tzinfo=None)
            else:
                published_at = message.date or datetime.now()

            return {
                'title': title,
                'url': self._extract_url(message, channel_username),
                'summary': summary,
                'source': channel_username,
                'published_at': published_at,
                'raw_text': text
            }
        except Exception as e:
            logger.warning(
                f"Ошибка при обработке сообщения {message.id}: {e}",
                exc_info=True
            )
            return None

    async def parse(self, limit: int = DEFAULT_PARSE_LIMIT) -> list[dict]:
        """Парсит сообщения из Telegram-канала."""
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
