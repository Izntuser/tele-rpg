"""Test-only support routes for the Playwright stack (``APP_ENV=test``).

Layers that keep this out of every other environment:
1. a router-level dependency answers 404 unless ``APP_ENV=test`` (checked per request, before
   authentication, so the route is indistinguishable from a missing one);
2. the routes are hidden from the OpenAPI schema;
3. the endpoint refuses (500) unless the connected database name ends in ``_e2e`` or ``_test``
   (``app.core.db_guard``), so even a mis-set APP_ENV cannot wipe a real database;
4. it still requires a valid JWT like every other ``/api`` route but ``/auth/telegram``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.engine import URL

from app.core import ratelimit
from app.core.config import Settings, get_settings
from app.core.db_guard import (
    E2E_DB_SUFFIX,
    TEST_DB_SUFFIX,
    UnsafeDatabaseError,
    assert_disposable_db,
)
from app.core.deps import CurrentUser, SessionDep
from app.db.base import Base, load_models


def require_test_env(settings: Annotated[Settings, Depends(get_settings)]) -> None:
    if settings.app_env != "test":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


router = APIRouter(
    prefix="/test",
    tags=["test"],
    include_in_schema=False,
    dependencies=[Depends(require_test_env)],
)


def _assert_disposable(url: URL) -> None:
    try:
        assert_disposable_db(url, suffix=E2E_DB_SUFFIX)
    except UnsafeDatabaseError:
        assert_disposable_db(url, suffix=TEST_DB_SUFFIX)


@router.post("/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset(_user: CurrentUser, session: SessionDep) -> None:
    """Truncate every application table (CASCADE) and clear the in-memory rate limits."""
    try:
        _assert_disposable(session.get_bind().engine.url)
    except UnsafeDatabaseError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="refusing to reset a non-disposable database",
        ) from None
    load_models()
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    await session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    await session.commit()
    ratelimit.reset_all()
