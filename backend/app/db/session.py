"""Application engine, session factory and the FastAPI session dependency.

Services own transactions: a route gets a session from ``get_session`` and the service calls
``commit()``; anything uncommitted is rolled back when the request ends.
"""

from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

# Pinned explicitly (it is also the Postgres default): the partnership_one_active_per_user trigger
# and the row-lock patterns in services are only correct under READ COMMITTED. See DECISIONS.md.
ISOLATION_LEVEL = "READ COMMITTED"


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.database_url.get_secret_value(),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        isolation_level=ISOLATION_LEVEL,
    )


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return make_sessionmaker(get_engine())


async def get_session() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency: one session per request, rolled back if left uncommitted."""
    async with get_sessionmaker()() as session:
        yield session


async def dispose_engine() -> None:
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()
