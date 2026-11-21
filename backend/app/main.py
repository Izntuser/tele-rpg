from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from sqlalchemy import text

from app.api.router import build_api_router
from app.core.config import get_settings
from app.core.db import make_engine

_API_PREFIXES = ("api", "healthz", "tg", "docs", "openapi.json")


def _dist_dir() -> Path:
    configured = get_settings().frontend_dist
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


def create_app() -> FastAPI:
    app = FastAPI(title="tele-rpg")
    engine = make_engine()

    @app.get("/healthz")
    async def healthz(response: Response) -> dict[str, str]:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("select 1"))
        except Exception:
            response.status_code = 503
            return {"status": "error", "db": "error"}
        return {"status": "ok", "db": "ok"}

    # Before the SPA catch-all, so /api/* never falls through to index.html.
    app.include_router(build_api_router())

    dist = _dist_dir()
    index = dist / "index.html"
    if index.is_file():

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str) -> FileResponse:
            if full_path.split("/", 1)[0] in _API_PREFIXES:
                raise HTTPException(status_code=404)
            candidate = (dist / full_path).resolve()
            if full_path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
                return FileResponse(candidate)
            return FileResponse(index)

    return app


app = create_app()
