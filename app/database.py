from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                    create_async_engine)
from sqlalchemy.orm import declarative_base

from app.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True,
    connect_args={
        "ssl": False
    }
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

Base = declarative_base()


async def init_db():
    async with engine.begin() as conn:
        from app import models  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:

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
    """Сохраняет объект в БД и обновляет его состояние."""
    if add:
        db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return obj


async def delete_and_flush(db: AsyncSession, obj):
    """Удаляет объект из БД."""
    await db.delete(obj)
    await db.flush()
