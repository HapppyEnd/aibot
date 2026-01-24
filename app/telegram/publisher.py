import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient
from telethon.errors import (ChannelInvalidError, FloodWaitError,
                             UsernameInvalidError)

from app.config import settings
from app.models import Post, PostStatus

logger = logging.getLogger(__name__)


class TelegramPublisher:
    """Класс для публикации постов в Telegram-канал."""

    def __init__(
        self,
        api_id: int | None = None,
        api_hash: str | None = None,
        channel_username: str | None = None
    ):

        self.api_id = api_id or settings.TELEGRAM_API_ID
        self.api_hash = api_hash or settings.TELEGRAM_API_HASH
        self.channel_username = (
            channel_username or settings.TELEGRAM_CHANNEL_USERNAME
        )

        if not self.api_id or not self.api_hash:
            raise ValueError(
                "Не указаны TELEGRAM_API_ID и TELEGRAM_API_HASH. ")

        if not self.channel_username:
            raise ValueError(
                "Не указан TELEGRAM_CHANNEL_USERNAME. ")

        session_name = getattr(
            settings, 'TELEGRAM_SESSION_NAME', 'telegram_session'
        )
        import os
        if os.path.exists('/app/telegram_sessions'):
            session_path = f'/app/telegram_sessions/{session_name}'
        else:
            session_path = session_name

        self.client = TelegramClient(
            session_path,
            self.api_id,
            self.api_hash
        )

    async def connect(self):
        """Подключиться к Telegram."""
        if not self.client.is_connected():
            try:
                await self.client.connect()
                if not await self.client.is_user_authorized():
                    raise ValueError(
                        "Сессия Telegram не авторизована. "
                        "Используйте API эндпоинт "
                        "/api/telegram/auth для авторизации."
                    )

                me = await self.client.get_me()
                if me:
                    logger.info(
                        f"Подключено к Telegram как {me.first_name} "
                        f"(@{me.username})"
                    )
                else:
                    logger.warning(
                        "Подключено к Telegram, но пользователь не авторизован"
                    )
            except ValueError:
                raise
            except Exception as e:
                logger.error(
                    f"Ошибка при подключении к Telegram: {e}. "
                    f"Убедитесь, что сессия авторизована. "
                    f"Используйте API эндпоинт /api/telegram/auth "
                    f"для авторизации."
                )
                raise

    async def disconnect(self):
        """Отключиться от Telegram."""
        if self.client.is_connected():
            await self.client.disconnect()
            logger.info("Отключено от Telegram")

    async def _mark_post_as_failed(
        self,
        post: Post | None,
        post_id: int | None,
        db: AsyncSession | None
    ) -> None:
        """Обновить статус поста на FAILED."""
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
        post_id: int | None = None,
        db: AsyncSession | None = None,
        channel_username: str | None = None
    ) -> int | None:
        """Опубликовать пост в канал."""
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

            max_retries = 3
            retry_count = 0
            while retry_count < max_retries:
                try:
                    message = await self.client.send_message(channel, text)
                    telegram_message_id = message.id
                    break
                except FloodWaitError as e:
                    wait_time = e.seconds
                    retry_count += 1
                    if retry_count < max_retries:
                        logger.warning(
                            f"Telegram FloodWait: нужно подождать "
                            f"{wait_time} секунд. "
                            f"Попытка {retry_count}/{max_retries}..."
                        )
                        import asyncio
                        await asyncio.sleep(wait_time + 1)
                    else:
                        logger.error(
                            f"Telegram FloodWait: превышен лимит после "
                            f"{max_retries} попыток. "
                            f"Нужно подождать {wait_time} секунд."
                        )
                        raise

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
                f"Пост успешно опубликован! "
                f"Telegram message ID: {telegram_message_id}"
                + (f", Post ID: {post_id}" if post_id else "")
            )
            return telegram_message_id

        except FloodWaitError as e:
            error_msg = (
                f"Telegram FloodWait: нужно подождать {e.seconds} секунд "
                f"перед следующей публикацией"
            )
            logger.error(error_msg)

            await self._mark_post_as_failed(post, post_id, db)
            return None
        except (ChannelInvalidError, UsernameInvalidError) as e:
            error_msg = (
                f"Ошибка: канал '{channel}' не найден "
                f"или недоступен: {e}"
            )
            logger.error(error_msg)

            await self._mark_post_as_failed(post, post_id, db)
            return None
        except Exception as e:
            error_msg = f"Ошибка при публикации поста: {e}"
            logger.error(error_msg, exc_info=True)

            await self._mark_post_as_failed(post, post_id, db)
            return None

    async def test_connection(self) -> bool:
        """Проверить подключение к Telegram и доступ к каналу."""
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
