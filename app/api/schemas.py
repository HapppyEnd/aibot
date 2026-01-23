"""
Pydantic схемы для валидации данных API
"""
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class SourceType(str, Enum):
    SITE = "site"
    TELEGRAM = "tg"


class PostStatus(str, Enum):
    NEW = "new"
    GENERATED = "generated"
    PUBLISHED = "published"
    FAILED = "failed"


class SourceBase(BaseModel):
    """
    Базовая схема источника новостей

    Поле url имеет разное значение в зависимости от type:
    - type='site': URL сайта (например, "https://habr.com")
    - type='tg': username Telegram-канала
    """
    type: SourceType
    name: str
    url: str  # URL для сайтов, username для Telegram-каналов
    enabled: bool = True


class SourceCreate(SourceBase):
    pass


class SourceUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    enabled: Optional[bool] = None


class SourceResponse(SourceBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class KeywordBase(BaseModel):
    word: str


class KeywordCreate(KeywordBase):
    pass


class KeywordResponse(KeywordBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class NewsItemResponse(BaseModel):
    id: str
    title: str
    url: Optional[str] = None
    summary: str
    source: str
    published_at: datetime
    raw_text: Optional[str] = None

    class Config:
        from_attributes = True


class PostCreate(BaseModel):
    """Схема для создания нового поста"""
    news_id: str
    generated_text: str
    status: PostStatus = PostStatus.NEW


class PostResponse(BaseModel):
    id: int
    news_id: str
    generated_text: str
    published_at: Optional[datetime] = None
    status: PostStatus
    created_at: datetime

    class Config:
        from_attributes = True


class GenerateRequest(BaseModel):
    news_id: Optional[str] = None
    text: Optional[str] = None
    custom_prompt: Optional[str] = None


class GenerateResponse(BaseModel):
    generated_text: str
    news_id: Optional[str] = None


class PublishRequest(BaseModel):
    """
    Запрос на публикацию поста

    Можно указать либо post_id (для публикации существующего поста),
    либо text (для публикации произвольного текста)
    """
    post_id: Optional[int] = None
    text: Optional[str] = None
    channel_username: Optional[str] = None


class PublishResponse(BaseModel):
    """Ответ на запрос публикации"""
    success: bool
    message: str
    telegram_message_id: Optional[int] = None
    post_id: Optional[int] = None


class TelegramAuthRequest(BaseModel):
    """Запрос на авторизацию в Telegram"""
    phone: str
    code: Optional[str] = None


class TelegramAuthResponse(BaseModel):
    """Ответ на запрос авторизации в Telegram"""
    success: bool
    message: str
    phone: Optional[str] = None
    username: Optional[str] = None
    next_step: Optional[str] = None
