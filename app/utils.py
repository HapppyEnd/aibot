"""
Утилиты для фильтрации и обработки новостей
"""
import hashlib
import logging

from langdetect import LangDetectException, detect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Keyword, NewsItem

logger = logging.getLogger(__name__)

DEFAULT_FILTER_REQUIRED_LANGUAGE: str | None = None
DEFAULT_FILTER_REQUIRED_SOURCE_IDS: list[int] | None = None
DEFAULT_FILTER_EXCLUDE_SOURCE_IDS: list[int] | None = None
DEFAULT_FILTER_CHECK_KEYWORDS: bool = False
DEFAULT_FILTER_CHECK_DUPLICATES: bool = True


def parse_source_ids(source_ids_str: str | None) -> list[int] | None:
    """
    Парсинг списка source_id из строки

    Args:
        source_ids_str: Строка с ID через запятую (например, "1,2,3")

    Returns:
        Список ID или None
    """
    if not source_ids_str:
        return None
    try:
        return [int(x.strip()) for x in source_ids_str.split(',') if x.strip()]
    except ValueError:
        logger.warning(f"Неверный формат source_ids: {source_ids_str}")
        return None


def detect_language(text: str) -> str:
    """
    Определение языка текста с помощью langdetect

    Args:
        text: Текст для анализа

    Returns:
        Код языка (ISO 639-1, например 'ru', 'en', 'de') или 'unknown'
    """
    if not text or len(text.strip()) < 3:
        return 'unknown'

    try:
        detected = detect(text)
        return detected
    except LangDetectException:
        logger.debug(f"Не удалось определить язык для текста: {text[:50]}...")
        return 'unknown'
    except Exception as e:
        logger.warning(f"Ошибка при определении языка: {e}")
        return 'unknown'


async def matches_keywords(
    news_item: NewsItem,
    keywords: list[str],
    db: AsyncSession | None = None
) -> bool:
    """
    Проверка, содержит ли новость ключевые слова

    Args:
        news_item: Новость для проверки
        keywords: Список ключевых слов
        db: Сессия БД (если None, используется keywords из параметра)

    Returns:
        True если новость содержит хотя бы одно ключевое слово
    """
    if not keywords:
        return True

    if db:
        result = await db.execute(select(Keyword))
        db_keywords = result.scalars().all()
        keywords = [kw.word.lower() for kw in db_keywords]

    text_to_search = f"{news_item.title} {news_item.summary}".lower()
    if news_item.raw_text:
        text_to_search += f" {news_item.raw_text.lower()}"

    keywords_lower = [kw.lower() for kw in keywords]
    return any(keyword in text_to_search for keyword in keywords_lower)


async def is_duplicate(
    news_item: NewsItem,
    db: AsyncSession
) -> bool:
    """
    Проверка, является ли новость дублем существующей

    Args:
        news_item: Новость для проверки
        db: Сессия БД

    Returns:
        True если найдена похожая новость (по URL или заголовку)
    """
    result = await db.execute(
        select(NewsItem).filter(NewsItem.id != news_item.id)
    )
    existing_news = result.scalars().all()

    if news_item.url:
        url_hash = hashlib.md5(news_item.url.encode()).hexdigest()
        for existing in existing_news:
            if existing.url:
                existing_url_hash = hashlib.md5(
                    existing.url.encode()
                ).hexdigest()
                if url_hash == existing_url_hash:
                    return True

    for existing in existing_news:
        if news_item.title.lower() == existing.title.lower():
            return True

    return False


async def should_generate_post(
    news_item: NewsItem,
    db: AsyncSession,
    required_language: str | None = DEFAULT_FILTER_REQUIRED_LANGUAGE,
    required_source_ids: list[int] | None = DEFAULT_FILTER_REQUIRED_SOURCE_IDS,
    exclude_source_ids: list[int] | None = DEFAULT_FILTER_EXCLUDE_SOURCE_IDS,
    check_keywords: bool = DEFAULT_FILTER_CHECK_KEYWORDS,
    check_duplicates: bool = DEFAULT_FILTER_CHECK_DUPLICATES
) -> tuple[bool, str]:
    """
    Проверка, нужно ли генерировать пост для новости

    Args:
        news_item: Новость для проверки
        db: Сессия БД
        required_language: Требуемый язык
        required_source_ids: Список разрешенных source_id
        exclude_source_ids: Список исключенных source_id
        check_keywords: Проверять ли ключевые слова
        check_duplicates: Проверять ли дубли

    Returns:
        Кортеж (should_generate, reason)
    """
    if required_language:
        news_text = f"{news_item.title} {news_item.summary}"
        detected_lang = detect_language(news_text)
        if detected_lang != required_language:
            return (
                False,
                f"Язык новости ({detected_lang}) не соответствует "
                f"требуемому ({required_language})"
            )

    if required_source_ids:
        if news_item.source_id not in required_source_ids:
            return (
                False,
                f"Источник {news_item.source_id} не в списке разрешенных"
            )

    if exclude_source_ids:
        if news_item.source_id in exclude_source_ids:
            return (
                False,
                f"Источник {news_item.source_id} в списке исключенных"
            )

    if check_keywords:
        result = await db.execute(select(Keyword))
        keywords = [kw.word for kw in result.scalars().all()]
        if keywords:
            if not await matches_keywords(news_item, keywords, db):
                return (
                    False,
                    "Новость не содержит ключевых слов"
                )

    if check_duplicates:
        if await is_duplicate(news_item, db):
            return (
                False,
                "Найдена похожая новость (дубль)"
            )

    return (True, "Новость прошла все проверки")
