from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.db import make_engine
from app.db.base import load_models
from app.db.session import ISOLATION_LEVEL, dispose_engine, get_engine, get_session
from app.modules.users.models import User
from tests import factories as f


async def test_get_session_uses_configured_pooled_engine() -> None:
    try:
        engine = get_engine()
        assert (
            engine.url.render_as_string(hide_password=False)
            == get_settings().database_url.get_secret_value()
        )
        assert engine.pool.size() == get_settings().db_pool_size  # type: ignore[attr-defined]
        gen = get_session()
        session = await anext(gen)
        assert isinstance(session, AsyncSession)
        assert (await session.execute(select(func.now()))).scalar_one() is not None
        await gen.aclose()
    finally:
        await dispose_engine()


async def test_app_engines_pin_read_committed() -> None:
    """The partnership one-active trigger relies on READ COMMITTED; it must not drift."""
    for engine in (get_engine(), make_engine()):
        try:
            async with engine.connect() as conn:
                level = (await conn.execute(text("SHOW transaction_isolation"))).scalar_one()
                assert await conn.get_isolation_level() == ISOLATION_LEVEL
            assert level == "read committed"
        finally:
            await engine.dispose()
    await dispose_engine()


async def test_session_fixture_commit_is_rolled_back_later(session: AsyncSession) -> None:
    """A service-style commit inside the isolated session does not end the outer transaction."""
    user = await f.create_user(session, display_name="committed-then-rolled-back")
    await session.commit()
    assert (await session.get(User, user.id)) is not None


async def test_previous_test_left_no_rows(session: AsyncSession) -> None:
    count = (
        await session.execute(
            select(func.count())
            .select_from(User)
            .where(User.display_name == "committed-then-rolled-back")
        )
    ).scalar_one()
    assert count == 0


async def test_independent_sessions_see_each_others_commits(
    independent_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with independent_sessions() as writer:
        user = await f.create_user(writer)
        await writer.commit()
    async with independent_sessions() as reader:
        assert (await reader.get(User, user.id)) is not None


def test_load_models_is_idempotent() -> None:
    load_models()
    load_models()
