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


# Source schemas
class SourceBase(BaseModel):
    type: SourceType
    name: str
    url: str
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


# Keyword schemas
class KeywordBase(BaseModel):
    word: str


class KeywordCreate(KeywordBase):
    pass


class KeywordResponse(KeywordBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


# NewsItem schemas
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


# Post schemas
class PostResponse(BaseModel):
    id: int
    news_id: str
    generated_text: str
    published_at: Optional[datetime] = None
    status: PostStatus
    created_at: datetime

    class Config:
        from_attributes = True


# Generate schemas
class GenerateRequest(BaseModel):
    news_id: Optional[str] = None
    text: Optional[str] = None
    custom_prompt: Optional[str] = None


class GenerateResponse(BaseModel):
    generated_text: str
    news_id: Optional[str] = None
