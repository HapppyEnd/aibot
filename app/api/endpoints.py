from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.api.schemas import (ErrorLogResponse, KeywordCreate, KeywordResponse,
                             NewsItemResponse, PostResponse, SourceCreate,
                             SourceResponse, SourceUpdate)
from app.database import get_db
from app.models import Keyword, NewsItem, Post, Source

router = APIRouter()


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
    db: Session = Depends(get_db)
):
    """
    Получить список всех источников новостей (сайты и Telegram-каналы).
    Поддерживает пагинацию и фильтрацию по статусу активности.
    """
    query = db.query(Source)

    if enabled is not None:
        query = query.filter(Source.enabled == enabled)

    sources = (
        query.order_by(desc(Source.created_at))
        .offset(skip)
        .limit(limit)
        .all()
    )
    return sources


@router.get(
    "/sources/{source_id}",
    response_model=SourceResponse,
    summary="Получить источник по ID"
)
async def get_source(source_id: int, db: Session = Depends(get_db)):
    """Получить информацию об источнике по его ID"""
    source = db.query(Source).filter(Source.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Источник не найден")
    return source


@router.post(
    "/sources/",
    response_model=SourceResponse,
    status_code=201,
    summary="Создать новый источник"
)
async def create_source(source: SourceCreate, db: Session = Depends(get_db)):
    """
    Создать новый источник новостей (сайт или Telegram-канал).
    
    - **type**: Тип источника (site или tg)
    - **name**: Название источника
    - **url**: URL сайта или username Telegram-канала
    - **enabled**: Активен ли источник (по умолчанию True)
    """
    db_source = Source(**source.dict())
    db.add(db_source)
    db.commit()
    db.refresh(db_source)
    return db_source


@router.put(
    "/sources/{source_id}",
    response_model=SourceResponse,
    summary="Обновить источник"
)
async def update_source(
    source_id: int,
    source_update: SourceUpdate,
    db: Session = Depends(get_db)
):
    """
    Обновить информацию об источнике.
    Можно обновить название, URL и статус активности.
    """
    db_source = db.query(Source).filter(Source.id == source_id).first()
    if not db_source:
        raise HTTPException(status_code=404, detail="Источник не найден")

    update_data = source_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_source, field, value)

    db.commit()
    db.refresh(db_source)
    return db_source


@router.delete(
    "/sources/{source_id}",
    status_code=204,
    summary="Удалить источник"
)
async def delete_source(source_id: int, db: Session = Depends(get_db)):
    """
    Удалить источник новостей.
    Внимание: это также удалит все связанные новости и логи ошибок.
    """
    db_source = db.query(Source).filter(Source.id == source_id).first()
    if not db_source:
        raise HTTPException(status_code=404, detail="Источник не найден")

    db.delete(db_source)
    db.commit()
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
    db: Session = Depends(get_db)
):
    """
    Получить список всех ключевых слов для фильтрации новостей.
    Поддерживает пагинацию.
    """
    keywords = (
        db.query(Keyword)
        .order_by(desc(Keyword.created_at))
        .offset(skip)
        .limit(limit)
        .all()
    )
    return keywords


@router.get(
    "/keywords/{keyword_id}",
    response_model=KeywordResponse,
    summary="Получить ключевое слово по ID"
)
async def get_keyword(keyword_id: int, db: Session = Depends(get_db)):
    """Получить информацию о ключевом слове по его ID"""
    keyword = db.query(Keyword).filter(Keyword.id == keyword_id).first()
    if not keyword:
        raise HTTPException(
            status_code=404, detail="Ключевое слово не найдено"
        )
    return keyword


@router.post(
    "/keywords/",
    response_model=KeywordResponse,
    status_code=201,
    summary="Добавить ключевое слово"
)
async def create_keyword(
    keyword: KeywordCreate, db: Session = Depends(get_db)
):
    """
    Добавить новое ключевое слово для фильтрации новостей.

    - **word**: Ключевое слово (должно быть уникальным)
    """
    existing = db.query(Keyword).filter(
        Keyword.word == keyword.word
    ).first()
    if existing:
        raise HTTPException(
            status_code=400, detail="Ключевое слово уже существует"
        )

    db_keyword = Keyword(**keyword.dict())
    db.add(db_keyword)
    db.commit()
    db.refresh(db_keyword)
    return db_keyword


@router.delete(
    "/keywords/{keyword_id}",
    status_code=204,
    summary="Удалить ключевое слово"
)
async def delete_keyword(keyword_id: int, db: Session = Depends(get_db)):
    """Удалить ключевое слово из списка фильтров"""
    db_keyword = (
        db.query(Keyword).filter(Keyword.id == keyword_id).first()
    )
    if not db_keyword:
        raise HTTPException(
            status_code=404, detail="Ключевое слово не найдено"
        )
    
    db.delete(db_keyword)
    db.commit()
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
    db: Session = Depends(get_db)
):
    """
    Получить историю всех постов.
    Поддерживает пагинацию и фильтрацию по статусу и ID новости.
    """
    query = db.query(Post)

    if status:
        query = query.filter(Post.status == status)

    if news_id:
        query = query.filter(Post.news_id == news_id)

    posts = (
        query.order_by(desc(Post.created_at))
        .offset(skip)
        .limit(limit)
        .all()
    )
    return posts


@router.get(
    "/posts/{post_id}",
    response_model=PostResponse,
    summary="Получить пост по ID"
)
async def get_post(post_id: int, db: Session = Depends(get_db)):
    """Получить информацию о посте по его ID"""
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Пост не найден")
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
    db: Session = Depends(get_db)
):
    """
    Получить список всех новостей.
    Поддерживает пагинацию и фильтрацию по источнику.
    """
    query = db.query(NewsItem)

    if source:
        query = query.filter(NewsItem.source == source)

    if source_id:
        query = query.filter(NewsItem.source_id == source_id)

    news = (
        query.order_by(desc(NewsItem.published_at))
        .offset(skip)
        .limit(limit)
        .all()
    )
    return news


@router.get(
    "/news/{news_id}",
    response_model=NewsItemResponse,
    summary="Получить новость по ID"
)
async def get_news_item(news_id: str, db: Session = Depends(get_db)):
    """Получить информацию о новости по её ID"""
    news_item = db.query(NewsItem).filter(NewsItem.id == news_id).first()
    if not news_item:
        raise HTTPException(status_code=404, detail="Новость не найдена")
    return news_item


def read_log_lines(
    log_file_path: Path, limit: int = 100, level_filter: Optional[str] = None
):
    """
    Читает последние строки из файла логов.

    level_filter: может быть одним уровнем (ERROR) или несколькими через |
                  (ERROR|WARNING). Если указан, фильтрует строки по уровню.
    """
    if not log_file_path.exists():
        return []

    try:
        with open(log_file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        recent_lines = lines[-limit:] if len(lines) > limit else lines

        if level_filter:
            allowed_levels = [
                level.strip().upper()
                for level in level_filter.split("|")
            ]
            filtered_lines = []
            for line in recent_lines:
                line_upper = line.upper()
                if any(level in line_upper for level in allowed_levels):
                    filtered_lines.append(line)
            recent_lines = filtered_lines

        logs = []
        for line in recent_lines:
            line = line.strip()
            if not line:
                continue

            parts = line.split(" - ")
            timestamp = parts[0] if len(parts) > 0 else ""
            level = ""
            if len(parts) > 2:
                for part in parts:
                    part_upper = part.strip().upper()
                    if part_upper in ["ERROR", "WARNING", "INFO", "DEBUG"]:
                        level = part_upper
                        break

            logs.append({
                "timestamp": timestamp,
                "level": level,
                "message": line,
                "module": None,
                "line": None
            })

        logs.reverse()
        return logs
    except Exception:
        return []


@router.get(
    "/logs/",
    response_model=List[ErrorLogResponse],
    summary="Получить логи ошибок"
)
async def get_error_logs(
    skip: int = Query(0, ge=0, description="Количество записей для пропуска"),
    limit: int = Query(
        100, ge=1, le=1000, description="Максимальное количество записей"
    ),
    level: Optional[str] = Query(
        None, description="Фильтр по уровню (ERROR, WARNING, INFO, DEBUG)"
    ),
):
    """
    Получить логи ошибок системы из файла.
    Поддерживает пагинацию и фильтрацию по уровню логирования.

    Уровни: ERROR, WARNING, INFO, DEBUG
    """
    log_file = Path("logs") / "aibot.log"

    read_limit = skip + limit
    all_logs = read_log_lines(log_file, limit=read_limit, level_filter=level)

    paginated_logs = all_logs[skip:skip + limit]

    return paginated_logs


@router.get(
    "/logs/recent",
    response_model=List[ErrorLogResponse],
    summary="Получить последние логи ошибок"
)
async def get_recent_error_logs(
    limit: int = Query(50, ge=1, le=500, description="Количество записей"),
    level: Optional[str] = Query(
        None, description="Фильтр по уровню (ERROR, WARNING)"
    ),
):
    """
    Получить последние логи ошибок (только ERROR и WARNING по умолчанию).
    Удобный эндпоинт для быстрого просмотра проблем.
    """
    log_file = Path("logs") / "aibot.log"

    level_filter = level or "ERROR|WARNING"
    all_logs = read_log_lines(log_file, limit=limit, level_filter=level_filter)

    return all_logs
