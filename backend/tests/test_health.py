from pathlib import Path

import httpx
import pytest

from app.core.config import get_settings
from app.main import create_app


async def test_healthz_ok() -> None:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": "ok"}


async def test_healthz_db_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@127.0.0.1:1/none")
    get_settings.cache_clear()
    try:
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            resp = await client.get("/healthz")
    finally:
        get_settings.cache_clear()
    assert resp.status_code == 503
    assert resp.json()["db"] == "error"


async def test_uses_test_database() -> None:
    assert get_settings().database_url.get_secret_value().endswith("/telerpg_test")


async def test_spa_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "index.html").write_text('<div id="root"></div>')
    monkeypatch.setenv("FRONTEND_DIST", str(tmp_path))
    get_settings.cache_clear()
    try:
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            page = await client.get("/some/route")
            api = await client.get("/api/nope")
    finally:
        get_settings.cache_clear()
    assert 'id="root"' in page.text
    assert page.headers["referrer-policy"] == "no-referrer"
    assert api.status_code == 404
