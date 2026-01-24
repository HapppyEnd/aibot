from datetime import datetime
from enum import Enum

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
    type: SourceType
    name: str
    url: str  # URL для сайтов, username для Telegram-каналов
    enabled: bool = True


class SourceCreate(SourceBase):
    pass


class SourceUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    enabled: bool | None = None


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
    url: str | None = None
    summary: str
    source: str
    published_at: datetime
    raw_text: str | None = None

    class Config:
        from_attributes = True


class PostCreate(BaseModel):
    news_id: str
    generated_text: str
    status: PostStatus = PostStatus.NEW


class PostUpdate(BaseModel):
    generated_text: str | None = None
    status: PostStatus | None = None


class PostResponse(BaseModel):
    id: int
    news_id: str
    generated_text: str
    published_at: datetime | None = None
    status: PostStatus
    created_at: datetime

    class Config:
        from_attributes = True


class GenerateRequest(BaseModel):
    news_id: str | None = None
    text: str | None = None
    custom_prompt: str | None = None


class GenerateResponse(BaseModel):
    generated_text: str
    news_id: str | None = None


class PublishRequest(BaseModel):
    post_id: int | None = None
    text: str | None = None
    channel_username: str | None = None


class PublishResponse(BaseModel):
    success: bool
    message: str
    telegram_message_id: int | None = None
    post_id: int | None = None


class TelegramAuthRequest(BaseModel):
    phone: str
    code: str | None = None


class TelegramAuthResponse(BaseModel):
    success: bool
    message: str
    phone: str | None = None
    username: str | None = None
    next_step: str | None = None
