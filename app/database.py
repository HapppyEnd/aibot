"""
Настройка подключения к базе данных (асинхронная версия)
"""
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                    create_async_engine)
from sqlalchemy.orm import declarative_base

from app.config import settings

# Создаем async движок БД
# Для PostgreSQL используем asyncpg драйвер
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True
)

# Создаем фабрику async сессий
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

# Базовый класс для моделей
Base = declarative_base()


async def init_db():
    """Инициализация базы данных - создание таблиц"""
    async with engine.begin() as conn:
        # Импортируем модели для создания таблиц
        # Импорт должен быть после определения Base
        from app import models  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:
    """
    Получить async сессию БД (для dependency injection в FastAPI)

    Usage:
        async def my_endpoint(db: AsyncSession = Depends(get_db)):
            result = await db.execute(select(MyModel))
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def save_and_refresh(
    db: AsyncSession,
    obj,
    add: bool = False
):
    """
    Сохраняет объект в БД и обновляет его состояние.

    Args:
        db: Async сессия БД
        obj: Объект для сохранения
        add: Если True, добавляет объект в сессию перед flush

    Returns:
        Обновленный объект
    """
    if add:
        db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return obj


async def delete_and_flush(db: AsyncSession, obj):
    """
    Удаляет объект из БД.

    Args:
        db: Async сессия БД
        obj: Объект для удаления
    """
    await db.delete(obj)
    await db.flush()
