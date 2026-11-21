import sys
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

import app.api.routes as routes_pkg
from app.api.router import build_api_router

DUMMY = """
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session

router = APIRouter(prefix="/dummy_s02")


@router.get("/ping")
async def ping(session: AsyncSession = Depends(get_session)) -> dict[str, int]:
    return {"one": (await session.execute(text("select 1"))).scalar_one()}
"""

NOT_A_ROUTE = "router = 'not an APIRouter'\n"


@pytest.fixture
def dummy_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Drop modules into a directory appended to ``app.api.routes.__path__``: they behave like
    new files in app/api/routes/ without touching the source tree."""
    monkeypatch.setattr(routes_pkg, "__path__", [*routes_pkg.__path__, str(tmp_path)])
    (tmp_path / "dummy_s02.py").write_text(DUMMY)
    (tmp_path / "not_a_route_s02.py").write_text(NOT_A_ROUTE)
    (tmp_path / "_private_s02.py").write_text("raise RuntimeError('must not import')\n")
    yield tmp_path
    for name in [m for m in sys.modules if m.startswith("app.api.routes.")]:
        if (getattr(sys.modules[name], "__file__", None) or "").startswith(str(tmp_path)):
            del sys.modules[name]


def test_build_api_router_includes_modules_exposing_router(dummy_route: Path) -> None:
    app = FastAPI()
    app.include_router(build_api_router())
    assert "/api/dummy_s02/ping" in app.openapi()["paths"]


async def test_new_route_module_is_mounted_in_the_app(
    dummy_route: Path, client: httpx.AsyncClient
) -> None:
    """The ``client`` fixture builds the app after ``dummy_route`` exists, and its session
    override serves the dummy route's ``get_session`` dependency."""
    resp = await client.get("/api/dummy_s02/ping")
    assert resp.status_code == 200
    assert resp.json() == {"one": 1}


async def test_unknown_api_path_is_404(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/does-not-exist")
    assert resp.status_code == 404
