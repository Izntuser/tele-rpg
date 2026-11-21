from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.db.session import ISOLATION_LEVEL


def make_engine() -> AsyncEngine:
    return create_async_engine(
        get_settings().database_url.get_secret_value(),
        poolclass=NullPool,
        isolation_level=ISOLATION_LEVEL,
    )
