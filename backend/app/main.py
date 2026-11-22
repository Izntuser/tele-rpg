import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from sqlalchemy import text

from app.api.router import build_api_router
from app.api.routes.notifications import dispatch_after_commit
from app.api.routes.tg_webhook import tg_router
from app.bot.dispatcher import close_bot, get_bot, setup_webhook
from app.core.config import get_settings
from app.core.db import make_engine
from app.core.logging import configure_logging
from app.storage.guard import check_storage_volume

log = logging.getLogger(__name__)

_HEALTH_TTL = 2.0  # seconds a /healthz DB result is reused
_API_PREFIXES = ("api", "healthz", "tg", "docs", "openapi.json")
# Invite tokens can sit in the SPA route (/invite/<token>); never leak them via Referer.
_SPA_HEADERS = {"Referrer-Policy": "no-referrer"}


def _dist_dir() -> Path:
    configured = get_settings().frontend_dist
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings)
    if settings.app_env == "prod":
        check_storage_volume(settings.storage_dir, allow_ephemeral=settings.storage_allow_ephemeral)
        try:
            await setup_webhook(get_bot(), settings)
            log.info("telegram webhook set")
        except Exception:
            log.exception("setting the Telegram webhook failed")
    try:
        yield
    finally:
        await close_bot()


def create_app() -> FastAPI:
    app = FastAPI(title="tele-rpg", lifespan=lifespan)
    engine = make_engine()
    # /healthz is public and uses NullPool (one new connection per check): serialize the DB check
    # and reuse its result for a couple of seconds so parallel requests cannot exhaust the pooler.
    health_gate = asyncio.Semaphore(1)
    last_check: tuple[float, bool] = (-_HEALTH_TTL, False)

    @app.get("/healthz")
    async def healthz(response: Response) -> dict[str, str]:
        nonlocal last_check
        async with health_gate:
            checked_at, ok = last_check
            if time.monotonic() - checked_at >= _HEALTH_TTL:
                try:
                    async with engine.connect() as conn:
                        await conn.execute(text("select 1"))
                    ok = True
                except Exception:
                    ok = False
                last_check = (time.monotonic(), ok)
        if not ok:
            response.status_code = 503
            return {"status": "error", "db": "error"}
        return {"status": "ok", "db": "ok"}

    # Before the SPA catch-all, so /api/* never falls through to index.html.
    # Every /api request sends the notifications it committed (outbox post-commit hook).
    app.include_router(build_api_router(), dependencies=[Depends(dispatch_after_commit)])
    app.include_router(tg_router)

    dist = _dist_dir()
    index = dist / "index.html"
    if index.is_file():

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str) -> FileResponse:
            if full_path.split("/", 1)[0] in _API_PREFIXES:
                raise HTTPException(status_code=404)
            candidate = (dist / full_path).resolve()
            if full_path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
                return FileResponse(candidate, headers=_SPA_HEADERS)
            return FileResponse(index, headers=_SPA_HEADERS)

    return app


app = create_app()
