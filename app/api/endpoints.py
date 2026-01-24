import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.generator import AIProviderError, PostGenerator
from app.api.helpers import (bad_request_error, create_publish_response,
                             not_found_error, server_error)
from app.api.schemas import (GenerateRequest, GenerateResponse, KeywordCreate,
                             KeywordResponse, NewsItemResponse, PostCreate,
                             PostResponse, PostUpdate, PublishRequest,
                             PublishResponse, SourceCreate, SourceResponse,
                             SourceUpdate, TelegramAuthRequest,
                             TelegramAuthResponse)
from app.config import settings
from app.database import delete_and_flush, get_db, save_and_refresh
from app.models import Keyword, NewsItem, Post, PostStatus, Source
from app.telegram.auth import authorize_telegram
from app.telegram.publisher import TelegramPublisher
from app.utils import matches_keywords, should_generate_post

router = APIRouter()
logger = logging.getLogger(__name__)

PAGINATION_SKIP = Query(0, ge=0, description="Количество записей для пропуска")
PAGINATION_LIMIT = Query(
    100, ge=1, le=1000, description="Максимальное количество записей")

MSG_PUBLISH_POST_OK = "Пост #{} успешно опубликован"
MSG_PUBLISH_POST_FAIL = "Не удалось опубликовать пост #{}"
MSG_PUBLISH_TEXT_OK = "Текст успешно опубликован"
MSG_PUBLISH_TEXT_FAIL = "Не удалось опубликовать текст"


async def create_or_update_post(
    db: AsyncSession,
    news_id: str,
    generated_text: str,
    status: PostStatus = PostStatus.GENERATED
) -> Post:
    """Создает новый пост или обновляет существующий."""

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
    response_model=list[SourceResponse],
    summary="Получить список всех источников"
)
async def get_sources(
    skip: int = PAGINATION_SKIP,
    limit: int = PAGINATION_LIMIT,
    enabled: bool | None = Query(
        None, description="Фильтр по статусу активности"
    ),
    db: AsyncSession = Depends(get_db)
):
    """Получить список всех источников новостей."""

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
    """Получить информацию об источнике по ID."""

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
    Создать новый источник новостей.

    - `type`: Тип источника
        - `site` - для веб-сайтов
        - `tg` - для Telegram-каналов
    - `name`: Название источника
    - `url`:
        - Для сайтов (`type=site`): URL сайта
        - Для Telegram (`type=tg`): username канала с @ или без
    - `enabled`: Активен ли источник (по умолчанию True)
    """
    db_source = Source(**source.model_dump())
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
    """Обновить информацию об источнике."""
    result = await db.execute(
        select(Source).filter(Source.id == source_id)
    )
    db_source = result.scalar_one_or_none()
    if not db_source:
        raise not_found_error("Источник не найден")

    update_data = source_update.model_dump(exclude_unset=True)
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
    Также удалит все связанные новости и посты.
    Задачи Celery, связанные с удаленными новостями, завершатся корректно
    (новость не найдена - это ожидаемое поведение).
    """
    result = await db.execute(
        select(Source).filter(Source.id == source_id)
    )
    db_source = result.scalar_one_or_none()
    if not db_source:
        raise not_found_error("Источник не найден")

    subq = select(NewsItem.id).where(NewsItem.source_id == source_id)
    await db.execute(delete(Post).where(Post.news_id.in_(subq)))
    await db.execute(delete(NewsItem).where(NewsItem.source_id == source_id))
    await delete_and_flush(db, db_source)
    return None


@router.get(
    "/keywords/",
    response_model=list[KeywordResponse],
    summary="Получить список всех ключевых слов"
)
async def get_keywords(
    skip: int = PAGINATION_SKIP,
    limit: int = PAGINATION_LIMIT,
    db: AsyncSession = Depends(get_db)
):
    """Получить список всех ключевых слов для фильтрации новостей."""

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
    """Получить ключевое слово по ID."""

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
    """Добавить новое ключевое слово."""

    result = await db.execute(
        select(Keyword).filter(Keyword.word == keyword.word)
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise bad_request_error("Ключевое слово уже существует")

    db_keyword = Keyword(**keyword.model_dump())
    await save_and_refresh(db, db_keyword, add=True)
    return db_keyword


@router.delete(
    "/keywords/{keyword_id}",
    status_code=204,
    summary="Удалить ключевое слово"
)
async def delete_keyword(keyword_id: int, db: AsyncSession = Depends(get_db)):
    """Удалить ключевое слово."""

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
    response_model=list[PostResponse],
    summary="Получить историю постов"
)
async def get_posts(
    skip: int = PAGINATION_SKIP,
    limit: int = PAGINATION_LIMIT,
    status: str | None = Query(
        None,
        description="Фильтр по статусу (new, generated, published, failed)"
    ),
    news_id: str | None = Query(None, description="Фильтр по ID новости"),
    db: AsyncSession = Depends(get_db)
):
    """Получить все посты."""

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
    """Создать новый пост вручную."""

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
    """Получить пост по ID."""

    result = await db.execute(
        select(Post).filter(Post.id == post_id)
    )
    post = result.scalar_one_or_none()
    if not post:
        raise not_found_error("Пост не найден")
    return post


@router.put(
    "/posts/{post_id}",
    response_model=PostResponse,
    summary="Обновить пост"
)
async def update_post(
    post_id: int,
    post_update: PostUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Обновить текст или статус поста."""
    result = await db.execute(
        select(Post).filter(Post.id == post_id)
    )
    post = result.scalar_one_or_none()
    if not post:
        raise not_found_error("Пост не найден")

    update_data = post_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(post, field, value)

    await save_and_refresh(db, post)
    return post


@router.delete(
    "/posts/{post_id}",
    status_code=204,
    summary="Удалить пост"
)
async def delete_post(post_id: int, db: AsyncSession = Depends(get_db)):
    """Удалить пост по ID."""
    result = await db.execute(
        select(Post).filter(Post.id == post_id)
    )
    post = result.scalar_one_or_none()
    if not post:
        raise not_found_error("Пост не найден")
    await delete_and_flush(db, post)
    return None


@router.get(
    "/news/",
    response_model=list[NewsItemResponse],
    summary="Получить список новостей"
)
async def get_news(
    skip: int = PAGINATION_SKIP,
    limit: int = PAGINATION_LIMIT,
    source: str | None = Query(
        None,
        description="Фильтр по названию источника"
    ),
    source_id: int | None = Query(
        None,
        description="Фильтр по ID источника"
    ),
    keyword: str | None = Query(
        None,
        description="Фильтр по ключевому слову"
    ),
    ready_for_generation: bool = Query(
        False,
        description="Только новости, готовые к генерации поста"
    ),
    db: AsyncSession = Depends(get_db)
):
    """Получить список новостей."""

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
    all_news = result.scalars().all()

    if ready_for_generation:
        filtered_news = []
        for news_item in all_news:
            should_generate, _ = await should_generate_post(
                news_item, db, check_keywords=False
            )
            if should_generate:
                filtered_news.append(news_item)
                if len(filtered_news) >= limit:
                    break
        return filtered_news

    if keyword:
        filtered_news = []
        for news_item in all_news:
            if await matches_keywords(news_item, [keyword], db=None):
                filtered_news.append(news_item)
                if len(filtered_news) >= limit:
                    break
        return filtered_news

    return all_news[:limit]


@router.get(
    "/news/{news_id}",
    response_model=NewsItemResponse,
    summary="Получить новость по ID"
)
async def get_news_item(news_id: str, db: AsyncSession = Depends(get_db)):
    """Получить новость по ID."""
    result = await db.execute(
        select(NewsItem).filter(NewsItem.id == news_id)
    )
    news_item = result.scalar_one_or_none()
    if not news_item:
        raise not_found_error("Новость не найдена")
    return news_item


@router.delete(
    "/news/{news_id}",
    status_code=204,
    summary="Удалить новость"
)
async def delete_news_item(news_id: str, db: AsyncSession = Depends(get_db)):
    """Удалить новость по ID. Также удалит все связанные посты."""
    result = await db.execute(
        select(NewsItem).filter(NewsItem.id == news_id)
    )
    news_item = result.scalar_one_or_none()
    if not news_item:
        raise not_found_error("Новость не найдена")

    await db.execute(delete(Post).where(Post.news_id == news_id))
    await delete_and_flush(db, news_item)
    return None


@router.post(
    "/generate",
    response_model=GenerateResponse,
    summary="Сгенерировать пост вручную"
)
async def generate_post(
    request: GenerateRequest,
    db: AsyncSession = Depends(get_db)
):
    """Сгенерировать пост."""
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
        raise bad_request_error("Необходимо указать news_id или text")

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
    """Публикация поста в Telegram-канал."""

    if not request.post_id and not request.text:
        raise bad_request_error("Необходимо указать post_id или text")

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
            post_id = request.post_id
            msg_ok = MSG_PUBLISH_POST_OK.format(post_id)
            msg_fail = MSG_PUBLISH_POST_FAIL.format(post_id)
        else:
            text_to_publish = request.text
            post_id = None
            msg_ok = MSG_PUBLISH_TEXT_OK
            msg_fail = MSG_PUBLISH_TEXT_FAIL

        telegram_message_id = await publisher.publish_post(
            text=text_to_publish,
            post_id=post_id,
            db=db if post_id else None
        )
        success = telegram_message_id is not None
        return create_publish_response(
            success=success,
            message=msg_ok if success else msg_fail,
            telegram_message_id=telegram_message_id,
            post_id=post_id
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при публикации поста: {e}", exc_info=True)
        raise server_error(f"Ошибка при публикации: {str(e)}")
    finally:
        await publisher.disconnect()


@router.post(
    "/telegram/auth",
    response_model=TelegramAuthResponse,
    summary="Авторизация в Telegram"
)
async def telegram_auth(request: TelegramAuthRequest):
    """
    Авторизация в Telegram через API.

    1. `Первый запрос` - отправка номера телефона:
       ```json
       {
         "phone": "+79991234567"
       }
       ```
       В ответ придет `next_step: "code"` - код из Telegram.

    2. `Второй запрос` - отправка кода:
       ```json
       {
         "phone": "+79991234567",
         "code": "12345"
       }
       ```
    """
    if not settings.TELEGRAM_API_ID or not settings.TELEGRAM_API_HASH:
        raise server_error("TELEGRAM_API_ID и TELEGRAM_API_HASH не настроены")

    if not request.phone:
        raise bad_request_error("Номер телефона не может быть пустым")

    result = await authorize_telegram(
        phone=request.phone,
        code=request.code
    )

    return TelegramAuthResponse(**result)
