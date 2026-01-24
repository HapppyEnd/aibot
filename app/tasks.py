import asyncio
import hashlib
import logging
from datetime import datetime, timezone

from celery import Celery
from sqlalchemy import select

from app.ai.generator import AIProviderError, PostGenerator
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import NewsItem, Post, PostStatus, Source, SourceType
from app.news_parser.sites import RSSParser
from app.news_parser.telegram import TelegramChannelParser
from app.telegram.publisher import TelegramPublisher
from app.utils import should_generate_post

logger = logging.getLogger(__name__)

TASK_TIME_LIMIT_SECONDS = 30 * 60
TASK_SOFT_TIME_LIMIT_SECONDS = 25 * 60
WORKER_PREFETCH_MULTIPLIER = 1

PARSE_SOURCES_INTERVAL_SECONDS = 1800.0
PROCESS_NEWS_INTERVAL_SECONDS = 1800.0

GENERATE_POST_RATE_LIMIT = '2/s'
PUBLISH_POST_RATE_LIMIT = '0.0033/s'

TELEGRAM_PARSE_LIMIT = 100
NEWS_ITEMS_PROCESS_LIMIT = 100
PUBLISH_BATCH_LIMIT = 10

GENERATE_DELAY_BASE_SECONDS = 10.0
GENERATE_DELAY_INCREMENT_SECONDS = 2.0
PUBLISH_DELAY_AFTER_GENERATION_SECONDS = 60
PUBLISH_BATCH_DELAY_SECONDS = 5

GENERATE_MAX_RETRIES = 3
GENERATE_RETRY_DELAY_SECONDS = 60
PUBLISH_MAX_RETRIES = 3
PUBLISH_RETRY_DELAY_SECONDS = 120

celery_app = Celery(
    'aibot',
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND
)

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=TASK_TIME_LIMIT_SECONDS,
    task_soft_time_limit=TASK_SOFT_TIME_LIMIT_SECONDS,
    worker_prefetch_multiplier=WORKER_PREFETCH_MULTIPLIER,
    task_acks_late=True,
    beat_schedule={
        'parse-all-sources': {
            'task': 'parse_all_sources',
            'schedule': PARSE_SOURCES_INTERVAL_SECONDS,
        },
        'process-news-items': {
            'task': 'process_news_items',
            'schedule': PROCESS_NEWS_INTERVAL_SECONDS,
        },
    },
    task_routes={
        'generate_post_for_news': {'rate_limit': GENERATE_POST_RATE_LIMIT},
    },
)


def run_async(coro):
    """
    Запускает async функцию в синхронном контексте Celery.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


async def _save_news_items(news_items: list[dict], source_id: int):
    """Сохраняет новости в БД."""

    async with AsyncSessionLocal() as db:
        saved_count = 0
        for item in news_items:
            try:
                news_id = hashlib.md5(
                    (item.get('url') or item.get('title', '')).encode()
                ).hexdigest()
                result = await db.execute(
                    select(NewsItem).filter(NewsItem.id == news_id)
                )
                existing = result.scalar_one_or_none()
                if existing:
                    continue
                published_at = (
                    item.get('published_at') or
                    datetime.now(timezone.utc)
                )
                if published_at.tzinfo is None:
                    published_at = published_at.replace(tzinfo=timezone.utc)
                news_item = NewsItem(
                    id=news_id,
                    title=item['title'],
                    url=item.get('url'),
                    summary=item.get('summary', ''),
                    source=item.get('source', ''),
                    source_id=source_id,
                    published_at=published_at,
                    raw_text=item.get('raw_text')
                )
                db.add(news_item)
                saved_count += 1
            except Exception as e:
                logger.error(
                    f"Ошибка при сохранении новости: {e}", exc_info=True)
                continue

        await db.commit()
        if saved_count > 0:
            logger.info(f"Сохранено {saved_count}/{len(news_items)} новостей")
        return saved_count


@celery_app.task(name='parse_all_sources')
def parse_all_sources():
    """Парсит все источники новостей."""

    run_async(_parse_all_sources_async())


async def _parse_all_sources_async():
    """Асинхронная функция для парсинга всех источников"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Source).filter(Source.enabled.is_(True))
        )
        sources = result.scalars().all()

        for source in sources:
            try:
                if source.type == SourceType.SITE:
                    if (source.url.endswith('.xml') or
                            source.url.endswith('.rss')):
                        parser = RSSParser(source.url, source.name)
                    else:
                        from app.news_parser.sites import UniversalHTMLParser
                        default_selectors = {
                            'container': (
                                'article, .article, .post, .news-item, .entry'
                            ),
                            'title': (
                                'h1, h2, h3, .title, .entry-title'
                            ),
                            'url': 'a',
                            'summary': (
                                'p, .summary, .excerpt, .description'
                            )
                        }
                        parser = UniversalHTMLParser(
                            url=source.url,
                            source_name=source.name,
                            selectors=default_selectors
                        )

                    news_items = parser.parse()
                    if news_items:
                        for item in news_items:
                            item['source'] = source.name
                        await _save_news_items(news_items, source.id)

                elif source.type == SourceType.TELEGRAM:
                    channel_username = source.url.lstrip('@')
                    parser = TelegramChannelParser(
                        channel_username=channel_username)
                    news_items = await parser.parse(limit=TELEGRAM_PARSE_LIMIT)
                    if news_items:
                        for item in news_items:
                            item['source'] = source.name
                        await _save_news_items(news_items, source.id)

            except Exception as e:
                logger.error(
                    f"Ошибка парсинга {source.name}: {e}", exc_info=True)


@celery_app.task(name='process_news_items')
def process_news_items():
    """Обрабатывает новые новости: фильтрация → генерация → публикация."""
    run_async(_process_news_items_async())


async def _process_news_items_async():
    """Асинхронная функция для обработки новостей."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(NewsItem)
            .join(Source, NewsItem.source_id == Source.id)
            .where(Source.enabled.is_(True))
            .order_by(NewsItem.published_at.desc())
            .limit(NEWS_ITEMS_PROCESS_LIMIT)
        )
        news_items = result.scalars().unique().all()
        processed_count = 0
        skipped_count = 0
        for news_item in news_items:
            try:
                should_generate, reason = await should_generate_post(
                    news_item, db,
                    check_keywords=False
                )
                if not should_generate:
                    skipped_count += 1
                    continue

                result_posts = await db.execute(
                    select(Post).filter(
                        Post.news_id == news_item.id,
                        Post.status == PostStatus.PUBLISHED
                    )
                )
                if result_posts.scalar_one_or_none():
                    skipped_count += 1
                    continue

                result_generating = await db.execute(
                    select(Post).filter(
                        Post.news_id == news_item.id,
                        Post.status.in_([PostStatus.GENERATED, PostStatus.NEW])
                    ).order_by(Post.id.desc())
                )
                if result_generating.scalar_one_or_none():
                    skipped_count += 1
                    continue

                if processed_count > 0:
                    delay = (
                        GENERATE_DELAY_BASE_SECONDS +
                        (processed_count * GENERATE_DELAY_INCREMENT_SECONDS)
                    )
                    await asyncio.sleep(delay)
                generate_post_for_news.delay(news_item.id)
                processed_count += 1
            except Exception as e:
                logger.error(
                    f"Ошибка при обработке новости {news_item.id}: {e}",
                    exc_info=True
                )
        logger.info(
            f"Обработка завершена: {processed_count} постов "
            f"запущено на генерацию, {skipped_count} пропущено"
        )


@celery_app.task(
    name='generate_post_for_news',
    rate_limit='0.1/s',
    max_retries=GENERATE_MAX_RETRIES,
    default_retry_delay=GENERATE_RETRY_DELAY_SECONDS
)
def generate_post_for_news(news_id: str):
    """Генерирует пост для новости."""
    return run_async(_generate_post_for_news_async(news_id))


async def _generate_post_for_news_async(news_id: str):
    """Асинхронная функция для генерации поста."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(NewsItem).filter(NewsItem.id == news_id)
        )
        news_item = result.scalar_one_or_none()

        if not news_item:
            logger.warning(f"Новость {news_id} не найдена")
            return None

        try:
            if news_item.raw_text:
                news_text = news_item.raw_text
            else:
                news_text = f"{news_item.title}\n\n{news_item.summary}"

            generator = PostGenerator()
            generated_text = await asyncio.to_thread(
                generator.generate_post,
                news_text=news_text
            )

            result_posts = await db.execute(
                select(Post).filter(
                    Post.news_id == news_id,
                    Post.status == PostStatus.GENERATED
                ).order_by(Post.id.desc())
            )
            existing_post = result_posts.scalar_one_or_none()

            if existing_post:
                existing_post.generated_text = generated_text
                post = existing_post
            else:
                post = Post(
                    news_id=news_id,
                    generated_text=generated_text,
                    status=PostStatus.GENERATED
                )
                db.add(post)

            await db.commit()
            await db.refresh(post)

            logger.info(f"Пост {post.id} сгенерирован для новости {news_id}")
            publish_post.apply_async(
                args=(post.id,),
                countdown=PUBLISH_DELAY_AFTER_GENERATION_SECONDS
            )
            return {"news_id": news_id, "post_id": post.id}
        except AIProviderError as e:
            logger.error(f"Ошибка AI генерации {news_id}: {e}")
        except Exception as e:
            logger.error(f"Ошибка генерации {news_id}: {e}", exc_info=True)
        return None


@celery_app.task(
    name='publish_post',
    rate_limit=PUBLISH_POST_RATE_LIMIT,
    max_retries=PUBLISH_MAX_RETRIES,
    default_retry_delay=PUBLISH_RETRY_DELAY_SECONDS
)
def publish_post(post_id: int):
    """Публикует пост в Telegram-канал."""
    run_async(_publish_post_async(post_id))


async def _publish_post_async(post_id: int):
    """Асинхронная функция для публикации поста."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Post).filter(Post.id == post_id)
        )
        post = result.scalar_one_or_none()
        if not post:
            return
        if post.status == PostStatus.PUBLISHED and post.published_at:
            return

        publisher = None
        try:
            publisher = TelegramPublisher()
            telegram_message_id = await publisher.publish_post(
                text=post.generated_text,
                post_id=post_id,
                db=db
            )
            if telegram_message_id:
                logger.info(f"Пост {post_id} опубликован")
            else:
                logger.error(f"Не удалось опубликовать пост {post_id}")
        except Exception as e:
            logger.error(f"Ошибка публикации {post_id}: {e}", exc_info=True)
        finally:
            if publisher:
                try:
                    await publisher.disconnect()
                except Exception:
                    pass
