import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tests.conftest import TEST_DATABASE_URL, alembic_config, truncate_all
from tests.db_guard import E2E_DB_SUFFIX, UnsafeDatabaseError, assert_disposable_db

PG = "postgresql+asyncpg://telerpg:telerpg@localhost:5432"


@pytest.mark.parametrize("name", ["telerpg_test", "anything_test"])
def test_test_databases_are_allowed(name: str) -> None:
    assert_disposable_db(f"{PG}/{name}")


@pytest.mark.parametrize("name", ["telerpg", "telerpg_e2e", "telerpg_test_prod", "_test", ""])
def test_other_databases_are_refused(name: str) -> None:
    with pytest.raises(UnsafeDatabaseError):
        assert_disposable_db(f"{PG}/{name}")


def test_e2e_suffix() -> None:
    assert_disposable_db(f"{PG}/telerpg_e2e", suffix=E2E_DB_SUFFIX)
    with pytest.raises(UnsafeDatabaseError):
        assert_disposable_db(f"{PG}/telerpg", suffix=E2E_DB_SUFFIX)
    with pytest.raises(UnsafeDatabaseError):
        assert_disposable_db(f"{PG}/telerpg_test", suffix=E2E_DB_SUFFIX)


def test_configured_test_database_passes_guard() -> None:
    assert_disposable_db(TEST_DATABASE_URL)


def test_alembic_config_refuses_non_test_database() -> None:
    with pytest.raises(UnsafeDatabaseError):
        alembic_config(f"{PG}/telerpg")


async def test_truncate_all_refuses_non_test_database_before_connecting() -> None:
    # An unreachable host proves the guard fires before any connection is attempted.
    engine = create_async_engine("postgresql+asyncpg://u:p@127.0.0.1:1/telerpg", poolclass=NullPool)
    try:
        with pytest.raises(UnsafeDatabaseError):
            await truncate_all(engine)
    finally:
        await engine.dispose()
