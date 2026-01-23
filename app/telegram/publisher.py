"""
Публикация постов в Telegram-канал через Telethon
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient
from telethon.errors import ChannelInvalidError, UsernameInvalidError

from app.config import settings
from app.models import Post, PostStatus

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

    async def _mark_post_as_failed(
        self,
        post: Optional[Post],
        post_id: Optional[int],
        db: Optional[AsyncSession]
    ) -> None:
        """
        Обновить статус поста на FAILED

        Args:
            post: Объект поста (если None, будет получен из БД по post_id)
            post_id: ID поста
            db: Сессия БД
        """
        if not post_id or not db:
            return

        if not post:
            result = await db.execute(
                select(Post).filter(Post.id == post_id)
            )
            post = result.scalar_one_or_none()

        if post:
            try:
                post.status = PostStatus.FAILED
                await db.commit()
                logger.info(f"Статус поста #{post_id} обновлен на FAILED")
            except Exception as db_error:
                logger.error(
                    f"Ошибка при обновлении статуса поста: {db_error}"
                )
                await db.rollback()

    async def publish_post(
        self,
        text: str,
        post_id: Optional[int] = None,
        db: Optional[AsyncSession] = None,
        channel_username: Optional[str] = None
    ) -> Optional[int]:
        """
        Опубликовать пост в канал

        Args:
            text: Текст поста для публикации
            post_id: ID поста в БД (для обновления статуса)
            db: Сессия БД (для проверки и обновления статуса)
            channel_username: Username канала
                (если не указан при инициализации)

        Returns:
            ID сообщения в Telegram или None при ошибке
        """
        if not text or not text.strip():
            error_msg = "Текст поста не может быть пустым"
            logger.error(error_msg)
            if post_id and db:
                await self._mark_post_as_failed(None, post_id, db)
            return None

        post = None
        if post_id and db:
            result = await db.execute(
                select(Post).filter(Post.id == post_id)
            )
            post = result.scalar_one_or_none()
            if post:
                if post.status == PostStatus.PUBLISHED and post.published_at:
                    logger.warning(
                        f"Пост #{post_id} уже был опубликован "
                        f"({post.published_at}). Пропускаем."
                    )
                    return None

        try:
            await self.connect()
            channel = channel_username or self.channel_username
            channel = channel.lstrip('@')
            logger.info(
                f"Публикация поста в канал: {channel}"
                + (f" (ID поста: {post_id})" if post_id else "")
            )
            message = await self.client.send_message(channel, text)
            telegram_message_id = message.id

            if post_id and db:
                try:
                    if post:
                        post.status = PostStatus.PUBLISHED
                        post.published_at = datetime.now(timezone.utc)
                        await db.commit()
                        logger.info(
                            f"Статус поста #{post_id} обновлен на PUBLISHED"
                        )
                except Exception as db_error:
                    logger.error(
                        f"Ошибка при обновлении статуса поста #{post_id}: "
                        f"{db_error}",
                        exc_info=True
                    )
                    await db.rollback()

            logger.info(
                f"✅ Пост успешно опубликован! "
                f"Telegram message ID: {telegram_message_id}"
                + (f", Post ID: {post_id}" if post_id else "")
            )
            return telegram_message_id

        except (ChannelInvalidError, UsernameInvalidError) as e:
            error_msg = (
                f"❌ Ошибка: канал '{channel}' не найден "
                f"или недоступен: {e}"
            )
            logger.error(error_msg)

            await self._mark_post_as_failed(post, post_id, db)
            return None
        except Exception as e:
            error_msg = f"❌ Ошибка при публикации поста: {e}"
            logger.error(error_msg, exc_info=True)

            await self._mark_post_as_failed(post, post_id, db)
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

            entity = await self.client.get_entity(channel)
            logger.info(f"Канал найден: {entity.title}")
            return True

        except (ChannelInvalidError, UsernameInvalidError) as e:
            logger.error(f"Канал '{channel}' недоступен: {e}")
            return False
        except Exception as e:
            logger.error(f"Ошибка при проверке канала: {e}", exc_info=True)
            return False
