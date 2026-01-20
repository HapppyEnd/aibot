"""
Модели данных для базы данных
"""
import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, Column, DateTime
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class SourceType(str, Enum):
    SITE = "site"
    TELEGRAM = "tg"


class PostStatus(str, Enum):
    NEW = "new"
    GENERATED = "generated"
    PUBLISHED = "published"
    FAILED = "failed"


class Source(Base):
    """Модель источника новостей"""
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(SQLEnum(SourceType), nullable=False)
    name = Column(String(255), nullable=False)
    url = Column(String(500), nullable=False)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # relationships
    news_items = relationship("NewsItem", back_populates="source_obj")


class Keyword(Base):
    """Модель ключевого слова для фильтрации"""
    __tablename__ = "keywords"

    id = Column(Integer, primary_key=True, index=True)
    word = Column(String(100), nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class NewsItem(Base):
    """Модель новости"""
    __tablename__ = "news_items"

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        nullable=False,
        unique=True
    )
    title = Column(String(500), nullable=False)
    url = Column(String(1000), nullable=True)
    summary = Column(Text, nullable=False)
    source = Column(String(255), nullable=False)  # Название источника
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=True)
    published_at = Column(DateTime, nullable=False)
    raw_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # relationships
    source_obj = relationship("Source", back_populates="news_items")
    posts = relationship("Post", back_populates="news_item")


class Post(Base):
    """Модель поста"""
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, index=True)
    news_id = Column(String(36), ForeignKey("news_items.id"), nullable=False)
    generated_text = Column(Text, nullable=False)
    published_at = Column(DateTime, nullable=True)
    status = Column(SQLEnum(PostStatus), default=PostStatus.NEW)
    created_at = Column(DateTime, default=datetime.utcnow)

    # relationships
    news_item = relationship("NewsItem", back_populates="posts")
