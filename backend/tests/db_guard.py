"""Refuse destructive test operations (TRUNCATE, ``alembic downgrade base``) against any
database whose name does not mark it as disposable: ``*_test`` for pytest, ``*_e2e`` for the
Playwright stack (use ``suffix=E2E_DB_SUFFIX`` there)."""

from sqlalchemy.engine import URL, make_url

TEST_DB_SUFFIX = "_test"
E2E_DB_SUFFIX = "_e2e"


class UnsafeDatabaseError(RuntimeError):
    pass


def assert_disposable_db(url: str | URL, suffix: str = TEST_DB_SUFFIX) -> None:
    name = make_url(url).database or ""
    if not name.endswith(suffix) or name == suffix:
        raise UnsafeDatabaseError(
            f"refusing destructive test operation on database {name!r}: "
            f"its name must end in {suffix!r}"
        )
