import asyncio
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.generator import AIProviderError, PostGenerator
from app.api.helpers import (bad_request_error, create_publish_response,
                             not_found_error, server_error)
from app.api.schemas import (GenerateRequest, GenerateResponse, KeywordCreate,
                             KeywordResponse, NewsItemResponse, PostCreate,
                             PostResponse, PublishRequest, PublishResponse,
                             SourceCreate, SourceResponse, SourceUpdate)
from app.config import settings
from app.database import delete_and_flush, get_db, save_and_refresh
from app.models import Keyword, NewsItem, Post, PostStatus, Source
from app.telegram.publisher import TelegramPublisher
from app.utils import should_generate_post

router = APIRouter()
logger = logging.getLogger(__name__)


async def create_or_update_post(
    db: AsyncSession,
    news_id: str,
    generated_text: str,
    status: PostStatus = PostStatus.GENERATED
) -> Post:
    """
    Создает новый пост или обновляет существующий для новости.

    Args:
        db: Async сессия БД
        news_id: ID новости
        generated_text: Сгенерированный текст поста
        status: Статус поста

    Returns:
        Созданный или обновленный пост
    """
    result = await db.execute(
        select(Post).filter(
            Post.news_id == news_id,
            Post.status == PostStatus.GENERATED
        )
    )
    existing_post = result.scalar_one_or_none()

    if existing_post:
        existing_post.generated_text = generated_text
        existing_post.status = status
        post = existing_post
    else:
        new_post = Post(
            news_id=news_id,
            generated_text=generated_text,
            status=status
        )
        db.add(new_post)
        post = new_post

    await save_and_refresh(db, post)
    return post


@router.get(
    "/sources/",
    response_model=List[SourceResponse],
    summary="Получить список всех источников"
)
async def get_sources(
    skip: int = Query(0, ge=0, description="Количество записей для пропуска"),
    limit: int = Query(
        100, ge=1, le=1000, description="Максимальное количество записей"
    ),
    enabled: Optional[bool] = Query(
        None, description="Фильтр по статусу активности"
    ),
    db: AsyncSession = Depends(get_db)
):
    """
    Получить список всех источников новостей (сайты и Telegram-каналы).
    Поддерживает пагинацию и фильтрацию по статусу активности.
    """
    query = select(Source)

    if enabled is not None:
        query = query.filter(Source.enabled == enabled)

    query = query.order_by(desc(Source.created_at)).offset(skip).limit(limit)

    result = await db.execute(query)
    sources = result.scalars().all()
    return sources


@router.get(
    "/sources/{source_id}",
    response_model=SourceResponse,
    summary="Получить источник по ID"
)
async def get_source(source_id: int, db: AsyncSession = Depends(get_db)):
    """Получить информацию об источнике по его ID"""
    result = await db.execute(
        select(Source).filter(Source.id == source_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise not_found_error("Источник не найден")
    return source


@router.post(
    "/sources/",
    response_model=SourceResponse,
    status_code=201,
    summary="Создать новый источник"
)
async def create_source(
    source: SourceCreate, db: AsyncSession = Depends(get_db)
):
    """
    Создать новый источник новостей (сайт или Telegram-канал).

    - `type`: Тип источника
        - `site` - для веб-сайтов
        - `tg` - для Telegram-каналов
    - `name`: Название источника (например, "Habr", "Мой канал")
    - `url`:
        - Для сайтов (`type=site`): URL сайта (например, "https://habr.com")
        - Для Telegram (`type=tg`): username канала с @ или без
          (например, "@channel_name" или "channel_name")
    - `enabled`: Активен ли источник (по умолчанию True)
    """
    db_source = Source(**source.dict())
    await save_and_refresh(db, db_source, add=True)
    return db_source


@router.put(
    "/sources/{source_id}",
    response_model=SourceResponse,
    summary="Обновить источник"
)
async def update_source(
    source_id: int,
    source_update: SourceUpdate,
    db: AsyncSession = Depends(get_db)
):
    """
    Обновить информацию об источнике.
    """
    result = await db.execute(
        select(Source).filter(Source.id == source_id)
    )
    db_source = result.scalar_one_or_none()
    if not db_source:
        raise not_found_error("Источник не найден")

    update_data = source_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_source, field, value)

    await save_and_refresh(db, db_source)
    return db_source


@router.delete(
    "/sources/{source_id}",
    status_code=204,
    summary="Удалить источник"
)
async def delete_source(source_id: int, db: AsyncSession = Depends(get_db)):
    """
    Удалить источник новостей.
    Внимание: это также удалит все связанные новости и логи ошибок.
    """
    result = await db.execute(
        select(Source).filter(Source.id == source_id)
    )
    db_source = result.scalar_one_or_none()
    if not db_source:
        raise not_found_error("Источник не найден")

    await delete_and_flush(db, db_source)
    return None


@router.get(
    "/keywords/",
    response_model=List[KeywordResponse],
    summary="Получить список всех ключевых слов"
)
async def get_keywords(
    skip: int = Query(0, ge=0, description="Количество записей для пропуска"),
    limit: int = Query(
        100, ge=1, le=1000, description="Максимальное количество записей"
    ),
    db: AsyncSession = Depends(get_db)
):
    """
    Получить список всех ключевых слов для фильтрации новостей.
    """
    query = (
        select(Keyword)
        .order_by(desc(Keyword.created_at))
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    keywords = result.scalars().all()
    return keywords


@router.get(
    "/keywords/{keyword_id}",
    response_model=KeywordResponse,
    summary="Получить ключевое слово по ID"
)
async def get_keyword(keyword_id: int, db: AsyncSession = Depends(get_db)):
    """Получить ключевое слово по ID"""
    result = await db.execute(
        select(Keyword).filter(Keyword.id == keyword_id)
    )
    keyword = result.scalar_one_or_none()
    if not keyword:
        raise not_found_error("Ключевое слово не найдено")
    return keyword


@router.post(
    "/keywords/",
    response_model=KeywordResponse,
    status_code=201,
    summary="Добавить ключевое слово"
)
async def create_keyword(
    keyword: KeywordCreate, db: AsyncSession = Depends(get_db)
):
    """
    Добавить новое ключевое слово для фильтрации новостей.

    - `word`: Ключевое слово (должно быть уникальным)
    """
    result = await db.execute(
        select(Keyword).filter(Keyword.word == keyword.word)
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise bad_request_error("Ключевое слово уже существует")

    db_keyword = Keyword(**keyword.dict())
    await save_and_refresh(db, db_keyword, add=True)
    return db_keyword


@router.delete(
    "/keywords/{keyword_id}",
    status_code=204,
    summary="Удалить ключевое слово"
)
async def delete_keyword(keyword_id: int, db: AsyncSession = Depends(get_db)):
    """Удалить ключевое слово из списка фильтров"""
    result = await db.execute(
        select(Keyword).filter(Keyword.id == keyword_id)
    )
    db_keyword = result.scalar_one_or_none()
    if not db_keyword:
        raise not_found_error("Ключевое слово не найдено")

    await delete_and_flush(db, db_keyword)
    return None


@router.get(
    "/posts/",
    response_model=List[PostResponse],
    summary="Получить историю постов"
)
async def get_posts(
    skip: int = Query(0, ge=0, description="Количество записей для пропуска"),
    limit: int = Query(
        100, ge=1, le=1000, description="Максимальное количество записей"
    ),
    status: Optional[str] = Query(
        None,
        description="Фильтр по статусу (new, generated, published, failed)"
    ),
    news_id: Optional[str] = Query(None, description="Фильтр по ID новости"),
    db: AsyncSession = Depends(get_db)
):
    """
    Получить историю всех постов.
    Поддерживает пагинацию и фильтрацию по статусу и ID новости.
    """
    query = select(Post)

    if status:
        query = query.filter(Post.status == status)

    if news_id:
        query = query.filter(Post.news_id == news_id)

    query = query.order_by(desc(Post.created_at)).offset(skip).limit(limit)

    result = await db.execute(query)
    posts = result.scalars().all()
    return posts


@router.post(
    "/posts/",
    response_model=PostResponse,
    status_code=201,
    summary="Создать новый пост вручную"
)
async def create_post(
    post: PostCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    Создать новый пост вручную.

    - `news_id`: ID новости из базы данных (обязательно)
    - `generated_text`: Текст поста для публикации
    - `status`: Статус поста (по умолчанию "new")
    """
    result = await db.execute(
        select(NewsItem).filter(NewsItem.id == post.news_id)
    )
    news_item = result.scalar_one_or_none()
    if not news_item:
        raise not_found_error(f"Новость с ID {post.news_id} не найдена")

    db_post = Post(
        news_id=post.news_id,
        generated_text=post.generated_text,
        status=post.status
    )
    await save_and_refresh(db, db_post, add=True)
    return db_post


@router.get(
    "/posts/{post_id}",
    response_model=PostResponse,
    summary="Получить пост по ID"
)
async def get_post(post_id: int, db: AsyncSession = Depends(get_db)):
    """Получить пост по ID"""
    result = await db.execute(
        select(Post).filter(Post.id == post_id)
    )
    post = result.scalar_one_or_none()
    if not post:
        raise not_found_error("Пост не найден")
    return post


@router.get(
    "/news/",
    response_model=List[NewsItemResponse],
    summary="Получить список новостей"
)
async def get_news(
    skip: int = Query(0, ge=0, description="Количество записей для пропуска"),
    limit: int = Query(
        100, ge=1, le=1000, description="Максимальное количество записей"
    ),
    source: Optional[str] = Query(
        None,
        description="Фильтр по названию источника"
    ),
    source_id: Optional[int] = Query(
        None,
        description="Фильтр по ID источника"
    ),
    db: AsyncSession = Depends(get_db)
):
    """
    Получить список всех новостей.
    """
    query = select(NewsItem)

    if source:
        query = query.filter(NewsItem.source == source)
    if source_id:
        query = query.filter(NewsItem.source_id == source_id)
    query = (
        query.order_by(desc(NewsItem.published_at))
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    news = result.scalars().all()
    return news


@router.get(
    "/news/filtered",
    response_model=List[NewsItemResponse],
    summary="Получить отфильтрованные новости для генерации"
)
async def get_filtered_news(
    skip: int = Query(0, ge=0, description="Количество записей для пропуска"),
    limit: int = Query(
        100, ge=1, le=1000, description="Максимальное количество записей"
    ),
    db: AsyncSession = Depends(get_db)
):
    """
    Получить список новостей, которые прошли фильтрацию и готовы
    к генерации постов.
    """
    query = (
        select(NewsItem)
        .order_by(desc(NewsItem.published_at))
        .offset(skip)
        .limit(limit * 3)
    )
    result = await db.execute(query)
    all_news = result.scalars().all()
    filtered_news = []
    for news_item in all_news:
        should_generate, _ = await should_generate_post(news_item, db)
        if should_generate:
            filtered_news.append(news_item)
            if len(filtered_news) >= limit:
                break

    return filtered_news


@router.get(
    "/news/{news_id}",
    response_model=NewsItemResponse,
    summary="Получить новость по ID"
)
async def get_news_item(news_id: str, db: AsyncSession = Depends(get_db)):
    """Получить новость по ID"""
    result = await db.execute(
        select(NewsItem).filter(NewsItem.id == news_id)
    )
    news_item = result.scalar_one_or_none()
    if not news_item:
        raise not_found_error("Новость не найдена")
    return news_item


@router.post(
    "/generate",
    response_model=GenerateResponse,
    summary="Сгенерировать пост вручную"
)
async def generate_post(
    request: GenerateRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Сгенерировать пост на основе новости или произвольного текста.
    Можно указать news_id для использования существующей новости,
    или передать text напрямую.

    - `news_id`: ID новости
    - `text`: Произвольный текст для генерации
    - `custom_prompt`: Промпт для генерации
    """
    generator = PostGenerator()

    if request.news_id:
        result = await db.execute(
            select(NewsItem).filter(NewsItem.id == request.news_id)
        )
        news_item = result.scalar_one_or_none()
        if not news_item:
            raise not_found_error("Новость не найдена")

        should_generate, reason = await should_generate_post(news_item, db)
        if not should_generate:
            raise bad_request_error(f"Новость не прошла фильтрацию: {reason}")

        news_text = f"{news_item.title}\n\n{news_item.summary}"
        if news_item.raw_text:
            news_text += f"\n\n{news_item.raw_text}"
    elif request.text:
        news_text = request.text
    else:
        raise bad_request_error("Необходимо указать либо news_id, либо text")

    try:
        generated_text = await asyncio.to_thread(
            generator.generate_post,
            news_text=news_text,
            custom_prompt=request.custom_prompt
        )

        if request.news_id:
            await create_or_update_post(
                db=db,
                news_id=request.news_id,
                generated_text=generated_text,
                status=PostStatus.GENERATED
            )

        return GenerateResponse(
            generated_text=generated_text,
            news_id=request.news_id
        )
    except ValueError as e:
        raise bad_request_error(str(e))
    except (AIProviderError, Exception) as e:
        logger.error(f"Ошибка при генерации поста: {e}", exc_info=True)
        raise server_error(f"Ошибка при генерации поста: {str(e)}")


@router.post(
    "/publish",
    response_model=PublishResponse,
    summary="Опубликовать пост в Telegram-канал вручную"
)
async def publish_post(
    request: PublishRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Публикация поста в Telegram-канал.

    - `post_id`: ID поста из БД
    - `text`: Произвольный текст для публикации
    - `channel_username`: Username канала
    """
    if not request.post_id and not request.text:
        raise bad_request_error("Необходимо указать либо post_id, либо text")

    if not settings.TELEGRAM_API_ID or not settings.TELEGRAM_API_HASH:
        raise server_error("TELEGRAM_API_ID и TELEGRAM_API_HASH не настроены")

    if not settings.TELEGRAM_CHANNEL_USERNAME and not request.channel_username:
        raise server_error("TELEGRAM_CHANNEL_USERNAME не настроен")

    channel = (
        request.channel_username or settings.TELEGRAM_CHANNEL_USERNAME
    )
    publisher = TelegramPublisher(
        api_id=settings.TELEGRAM_API_ID,
        api_hash=settings.TELEGRAM_API_HASH,
        channel_username=channel
    )

    try:
        if request.post_id:
            result = await db.execute(
                select(Post).filter(Post.id == request.post_id)
            )
            post = result.scalar_one_or_none()
            if not post:
                raise not_found_error(f"Пост с ID {request.post_id} не найден")

            if post.status == PostStatus.PUBLISHED and post.published_at:
                return create_publish_response(
                    success=False,
                    message=f"Пост #{request.post_id} уже был опубликован",
                    post_id=request.post_id
                )

            text_to_publish = post.generated_text
            telegram_message_id = await publisher.publish_post(
                text=text_to_publish,
                post_id=request.post_id,
                db=db
            )
            success = telegram_message_id is not None
            return create_publish_response(
                success=success,
                message=(
                    f"Пост #{request.post_id} успешно опубликован"
                    if success
                    else f"Не удалось опубликовать пост #{request.post_id}"
                ),
                telegram_message_id=telegram_message_id,
                post_id=request.post_id
            )

        elif request.text:
            telegram_message_id = await publisher.publish_post(
                text=request.text
            )
            success = telegram_message_id is not None
            return create_publish_response(
                success=success,
                message=(
                    "Текст успешно опубликован"
                    if success
                    else "Не удалось опубликовать текст"
                ),
                telegram_message_id=telegram_message_id
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при публикации поста: {e}", exc_info=True)
        raise server_error(f"Ошибка при публикации: {str(e)}")
    finally:
        await publisher.disconnect()
