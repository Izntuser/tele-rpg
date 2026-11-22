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


async def test_healthz_parallel_calls_open_one_connection_at_a_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from app import main

    live = peak = opened = 0

    class FakeConn:
        async def __aenter__(self) -> "FakeConn":
            nonlocal live, peak, opened
            live += 1
            opened += 1
            peak = max(peak, live)
            return self

        async def __aexit__(self, *_a: object) -> None:
            nonlocal live
            live -= 1

        async def execute(self, _stmt: object) -> None:
            await asyncio.sleep(0.05)

    class FakeEngine:
        def connect(self) -> FakeConn:
            return FakeConn()

    monkeypatch.setattr(main, "make_engine", lambda: FakeEngine())
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resps = await asyncio.gather(*[client.get("/healthz") for _ in range(20)])
    assert all(r.status_code == 200 for r in resps)
    assert peak == 1
    assert opened == 1  # the rest reuse the cached result
