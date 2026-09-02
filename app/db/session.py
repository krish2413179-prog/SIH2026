"""SQLAlchemy async engine and session factory.

Usage in FastAPI route handlers:
    async def my_route(db: AsyncSession = Depends(get_db)):
        result = await db.execute(select(MyModel))
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

settings = get_settings()

# Async engine — used by FastAPI routes and Celery tasks via run_sync
connect_args = {}
if "asyncpg" in settings.database_url:
    connect_args = {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
    }

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_recycle=3600,
    connect_args=connect_args,
)

# Session factory — each request gets its own session
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields an async database session.

    The session is automatically committed on success and rolled back
    on any exception, then closed regardless.
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
