"""
Celery задачи для фоновой обработки
"""
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
PUBLISH_POSTS_INTERVAL_SECONDS = 600.0

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
        'publish-generated-posts': {
            'task': 'publish_generated_posts',
            'schedule': PUBLISH_POSTS_INTERVAL_SECONDS,
        },
    },
    task_routes={
        'generate_post_for_news': {'rate_limit': GENERATE_POST_RATE_LIMIT},
    },
)


def run_async(coro):
    """
    Запускает async функцию в синхронном контексте Celery

    Args:
        coro: Coroutine для выполнения

    Returns:
        Результат выполнения coroutine
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


async def _save_news_items(news_items: list[dict], source_id: int):
    """
    Сохраняет новости в БД

    Args:
        news_items: Список словарей с новостями
        source_id: ID источника
    """
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
                    title_preview = item.get('title', '')[:50]
                    logger.debug(
                        f"Новость уже существует в БД: {title_preview}..."
                    )
                    continue

                published_at = item.get('published_at')
                if not published_at:
                    published_at = datetime.now(timezone.utc)
                elif published_at.tzinfo is None:
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
        if saved_count == 0:
            logger.info(
                f"Все новости уже есть в БД: сохранено {saved_count} новых "
                f"из {len(news_items)} обработанных"
            )
        else:
            logger.info(
                f"Сохранено {saved_count} новых новостей из {len(news_items)}")
        return saved_count


@celery_app.task(name='parse_all_sources')
def parse_all_sources():
    """
    Парсит все активные источники новостей
    Запускается по расписанию через Celery Beat
    """
    logger.info("Начало парсинга всех источников")
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
                    parse_site_source.delay(source.id)
                elif source.type == SourceType.TELEGRAM:
                    parse_telegram_source.delay(source.id)
            except Exception as e:
                logger.error(
                    f"Ошибка при запуске парсинга источника {source.id}: {e}",
                    exc_info=True
                )


@celery_app.task(name='parse_site_source')
def parse_site_source(source_id: int):
    """
    Парсит новости с сайта

    Args:
        source_id: ID источника в БД
    """
    logger.info(f"Парсинг сайта source_id={source_id}")
    run_async(_parse_site_source_async(source_id))


async def _parse_site_source_async(source_id: int):
    """Асинхронная функция для парсинга сайта"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Source).filter(Source.id == source_id)
        )
        source = result.scalar_one_or_none()

        if not source or not source.enabled:
            logger.warning(f"Источник {source_id} не найден или отключен")
            return

        try:
            logger.info(
                f"Начало парсинга сайта {source.name} (URL: {source.url})"
            )

            if source.url.endswith('.xml') or source.url.endswith('.rss'):
                logger.debug(f"Используется RSS парсер для {source.url}")
                parser = RSSParser(source.url, source.name)
            elif 'habr.com' in source.url:
                logger.debug(f"Используется Habr парсер для {source.url}")
                from app.news_parser.sites import HabrParser
                parser = HabrParser()
            else:
                logger.debug(
                    f"Используется универсальный HTML парсер для "
                    f"{source.url}"
                )
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
                    ),
                    'date': 'time, .date, .published'
                }
                parser = UniversalHTMLParser(
                    url=source.url,
                    source_name=source.name,
                    selectors=default_selectors
                )

            logger.debug(f"Запуск парсинга для {source.name}...")
            news_items = parser.parse()
            items_count = len(news_items) if news_items else 0
            logger.debug(f"Парсер вернул {items_count} новостей")

            if news_items:
                for item in news_items:
                    item['source'] = source.name
                saved_count = await _save_news_items(news_items, source_id)
                logger.info(
                    f"Парсинг сайта {source.name} завершен: "
                    f"найдено {len(news_items)} новостей, "
                    f"сохранено {saved_count} новых"
                )
            else:
                logger.warning(
                    f"Парсинг сайта {source.name} не вернул новостей. "
                    f"Возможно, селекторы не подходят для этого сайта "
                    f"или сайт недоступен."
                )
        except ValueError as e:
            logger.error(
                f"Ошибка конфигурации парсера для сайта {source.name}: {e}",
                exc_info=True
            )
        except Exception as e:
            logger.error(
                f"Ошибка при парсинге сайта {source.name} "
                f"(URL: {source.url}): {e}",
                exc_info=True
            )


@celery_app.task(name='parse_telegram_source')
def parse_telegram_source(source_id: int):
    """
    Парсит новости из Telegram-канала

    Args:
        source_id: ID источника в БД
    """
    logger.info(f"Парсинг Telegram канала source_id={source_id}")
    run_async(_parse_telegram_source_async(source_id))


async def _parse_telegram_source_async(source_id: int):
    """Асинхронная функция для парсинга Telegram канала"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Source).filter(Source.id == source_id)
        )
        source = result.scalar_one_or_none()

        if not source or not source.enabled:
            logger.warning(f"Источник {source_id} не найден или отключен")
            return

        try:
            channel_username = source.url.lstrip('@')
            parser = TelegramChannelParser(channel_username=channel_username)
            news_items = await parser.parse(limit=TELEGRAM_PARSE_LIMIT)

            if news_items:
                for item in news_items:
                    item['source'] = source.name
                await _save_news_items(news_items, source_id)
                logger.info(
                    f"Парсинг Telegram канала {source.name} завершен: "
                    f"{len(news_items)} новостей"
                )
        except Exception as e:
            logger.error(
                f"Ошибка при парсинге Telegram канала {source.name}: {e}",
                exc_info=True
            )


@celery_app.task(name='process_news_items')
def process_news_items():
    """
    Обрабатывает новые новости: фильтрация → генерация → публикация
    Запускается по расписанию через Celery Beat
    """
    logger.info("Начало обработки новостей")
    run_async(_process_news_items_async())


async def _process_news_items_async():
    """Асинхронная функция для обработки новостей"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(NewsItem)
            .order_by(NewsItem.published_at.desc())
            .limit(NEWS_ITEMS_PROCESS_LIMIT)
        )
        news_items = result.scalars().all()

        logger.info(
            f"Обработка {len(news_items)} новостей для генерации постов"
        )

        sources_count = {}
        for item in news_items:
            source = item.source or 'unknown'
            sources_count[source] = sources_count.get(source, 0) + 1
        logger.info(f"Распределение по источникам: {sources_count}")

        processed_count = 0
        skipped_count = 0
        for news_item in news_items:
            try:
                should_generate, reason = await should_generate_post(
                    news_item, db,
                    check_keywords=False
                )
                if not should_generate:
                    title_preview = news_item.title[:50]
                    logger.info(
                        f"Новость {news_item.id} ({title_preview}...) "
                        f"[{news_item.source}] пропущена: {reason}"
                    )
                    skipped_count += 1
                    continue

                result_posts = await db.execute(
                    select(Post).filter(
                        Post.news_id == news_item.id,
                        Post.status == PostStatus.PUBLISHED
                    )
                )
                published_post = result_posts.scalar_one_or_none()

                if published_post:
                    title_preview = news_item.title[:50]
                    logger.info(
                        f"Пост для новости {news_item.id} "
                        f"({title_preview}...) уже опубликован"
                    )
                    skipped_count += 1
                    continue

                result_generating = await db.execute(
                    select(Post).filter(
                        Post.news_id == news_item.id,
                        Post.status.in_([PostStatus.GENERATED, PostStatus.NEW])
                    ).order_by(Post.id.desc())
                )
                generating_post = result_generating.scalar_one_or_none()

                if generating_post:
                    title_preview = news_item.title[:50]
                    logger.info(
                        f"Пост для новости {news_item.id} "
                        f"({title_preview}...) уже в процессе обработки "
                        f"(статус: {generating_post.status})"
                    )
                    skipped_count += 1
                    continue

                title_preview = news_item.title[:50]
                logger.info(
                    f"Запуск генерации поста для новости {news_item.id}: "
                    f"{title_preview}..."
                )
                import time
                if processed_count > 0:
                    delay = (
                        GENERATE_DELAY_BASE_SECONDS +
                        (processed_count * GENERATE_DELAY_INCREMENT_SECONDS)
                    )
                    logger.debug(
                        f"Задержка перед запуском задачи генерации: "
                        f"{delay:.1f} сек"
                    )
                    time.sleep(delay)
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
    """
    Генерирует пост для новости

    Args:
        news_id: ID новости
    """
    logger.info(f"Генерация поста для новости {news_id}")
    run_async(_generate_post_for_news_async(news_id))


async def _generate_post_for_news_async(news_id: str):
    """Асинхронная функция для генерации поста"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(NewsItem).filter(NewsItem.id == news_id)
        )
        news_item = result.scalar_one_or_none()

        if not news_item:
            logger.warning(f"Новость {news_id} не найдена")
            return

        try:
            news_text = f"{news_item.title}\n\n{news_item.summary}"
            if news_item.raw_text:
                news_text += f"\n\n{news_item.raw_text}"

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

            logger.info(
                f"Пост сгенерирован для новости {news_id}, "
                f"post_id={post.id}. Длина текста: "
                f"{len(generated_text)} символов. Запуск публикации..."
            )
            import time
            time.sleep(PUBLISH_DELAY_AFTER_GENERATION_SECONDS)
            publish_post.delay(post.id)
        except AIProviderError as e:
            logger.error(f"Ошибка AI при генерации поста: {e}")
        except Exception as e:
            logger.error(
                f"Ошибка при генерации поста для новости {news_id}: {e}",
                exc_info=True
            )


@celery_app.task(
    name='publish_post',
    rate_limit=PUBLISH_POST_RATE_LIMIT,
    max_retries=PUBLISH_MAX_RETRIES,
    default_retry_delay=PUBLISH_RETRY_DELAY_SECONDS
)
def publish_post(post_id: int):
    """
    Публикует пост в Telegram-канал

    Args:
        post_id: ID поста в БД
    """
    logger.info(f"Публикация поста {post_id}")
    run_async(_publish_post_async(post_id))


async def _publish_post_async(post_id: int):
    """Асинхронная функция для публикации поста"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Post).filter(Post.id == post_id)
        )
        post = result.scalar_one_or_none()

        if not post:
            logger.warning(f"Пост {post_id} не найден")
            return

        if post.status == PostStatus.PUBLISHED and post.published_at:
            logger.info(f"Пост {post_id} уже опубликован")
            return

        publisher = None
        try:
            text_length = (
                len(post.generated_text) if post.generated_text else 0
            )
            logger.info(
                f"Начало публикации поста {post_id}. "
                f"Статус: {post.status}, длина текста: {text_length}"
            )

            publisher = TelegramPublisher()
            telegram_message_id = await publisher.publish_post(
                text=post.generated_text,
                post_id=post_id,
                db=db
            )

            if telegram_message_id:
                logger.info(
                    f"Пост {post_id} успешно опубликован, "
                    f"telegram_message_id={telegram_message_id}"
                )
            else:
                post.status = PostStatus.FAILED
                await db.commit()
                logger.error(
                    f"Не удалось опубликовать пост {post_id}. "
                    f"publish_post вернул None"
                )
        except Exception as e:
            logger.error(
                f"Ошибка при публикации поста {post_id}: {e}",
                exc_info=True
            )
            post.status = PostStatus.FAILED
            await db.commit()
        finally:
            if publisher:
                try:
                    await publisher.disconnect()
                except Exception as e:
                    logger.warning(f"Ошибка при отключении от Telegram: {e}")


@celery_app.task(name='publish_generated_posts')
def publish_generated_posts():
    """
    Публикует все посты со статусом GENERATED
    Запускается по расписанию через Celery Beat
    """
    logger.info("Начало публикации постов со статусом GENERATED")
    run_async(_publish_generated_posts_async())


async def _publish_generated_posts_async():
    """Асинхронная функция для публикации всех постов со статусом GENERATED"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Post).filter(Post.status == PostStatus.GENERATED)
            .order_by(Post.id.asc())
            .limit(PUBLISH_BATCH_LIMIT)
        )
        posts = result.scalars().all()

        logger.info(
            f"Найдено {len(posts)} постов со статусом GENERATED "
            f"для публикации"
        )

        published_count = 0
        for post in posts:
            try:
                logger.info(f"Запуск публикации поста {post.id}")
                publish_post.delay(post.id)
                published_count += 1
                await asyncio.sleep(PUBLISH_BATCH_DELAY_SECONDS)
            except Exception as e:
                logger.error(
                    f"Ошибка при запуске публикации поста {post.id}: {e}",
                    exc_info=True
                )

        logger.info(
            f"Публикация завершена: запущено {published_count} "
            f"задач публикации из {len(posts)} найденных постов"
        )
