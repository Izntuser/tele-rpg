import os

# Must run before app modules are imported: pytest uses the telerpg_test database.
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://telerpg:telerpg@localhost:5432/telerpg_test"
)
os.environ["FRONTEND_DIST"] = "/nonexistent"

from collections.abc import AsyncIterator, Iterator  # noqa: E402
from datetime import UTC, datetime  # noqa: E402
from pathlib import Path  # noqa: E402
from types import ModuleType  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

from app.core import clock  # noqa: E402
from app.db.base import Base, load_models  # noqa: E402
from app.db.session import get_session, make_sessionmaker  # noqa: E402

TEST_DATABASE_URL = os.environ["DATABASE_URL"]
BACKEND_DIR = Path(__file__).resolve().parents[1]
FROZEN_AT = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)

load_models()


def alembic_config(database_url: str = TEST_DATABASE_URL) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.attributes["database_url"] = database_url
    return cfg


@pytest.fixture(scope="session", autouse=True)
def _migrated_test_db() -> None:
    """Bring telerpg_test to head once per run (sync: alembic's env.py runs its own loop)."""
    command.upgrade(alembic_config(), "head")


@pytest.fixture
async def db_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Per-test isolated session: everything runs inside one outer transaction that is rolled
    back at teardown. ``session.commit()`` in code under test only releases a SAVEPOINT, so
    services can commit normally and nothing leaks between tests."""
    async with db_engine.connect() as conn:
        outer = await conn.begin()
        s = AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        try:
            yield s
        finally:
            await s.close()
            if outer.is_active:
                await outer.rollback()


async def truncate_all(engine: AsyncEngine) -> None:
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def independent_sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Session factory for concurrency tests: every ``factory()`` session gets its own pooled
    connection and really commits, so row locks and constraints race as in production.
    All tables are truncated at teardown. Do not combine with the ``session`` fixture in one
    test (its open outer transaction would block the TRUNCATE)."""
    engine = create_async_engine(TEST_DATABASE_URL, pool_size=20, max_overflow=0)
    try:
        yield make_sessionmaker(engine)
    finally:
        await engine.dispose()
        cleanup = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        try:
            await truncate_all(cleanup)
        finally:
            await cleanup.dispose()


@pytest.fixture
def frozen_clock() -> Iterator[ModuleType]:
    """Freeze ``app.core.clock`` at FROZEN_AT; use ``frozen_clock.freeze/advance`` to move it."""
    clock.freeze(FROZEN_AT)
    try:
        yield clock
    finally:
        clock.unfreeze()


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP client against a fresh app whose ``get_session`` yields the isolated test session."""
    from app.main import create_app

    app = create_app()

    async def _session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
