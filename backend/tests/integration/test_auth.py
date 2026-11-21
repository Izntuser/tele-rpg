import re
from collections.abc import AsyncIterator
from datetime import timedelta
from types import ModuleType
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode

import httpx
import jwt as pyjwt
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import test_support
from app.core import ratelimit
from app.core.config import Settings, get_settings
from app.core.db_guard import UnsafeDatabaseError
from app.core.deps import CurrentUser
from app.db.session import get_session
from app.modules.auth.jwt import AUDIENCE, ISSUER, encode_token
from app.modules.common.enums import Locale
from app.modules.users.models import User
from tests import factories
from tests.telegram_sign import make_init_data

DAY = timedelta(hours=24)
PROBE = "/api/__probe_write"
App = tuple[FastAPI, httpx.AsyncClient]


@pytest.fixture(autouse=True)
def _clean_limiters() -> None:
    ratelimit.reset_all()


@pytest.fixture
async def app_client(session: AsyncSession) -> AsyncIterator[App]:
    """A fresh app bound to the rolled-back test session (like ``client``, but exposing the app
    so tests can override settings or add a probe write route)."""
    from app.main import create_app

    app = create_app()

    async def _session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield app, c


@pytest.fixture
def client_(app_client: App) -> httpx.AsyncClient:
    return app_client[1]


def settings() -> Settings:
    return get_settings()


def token_for(user_id: int, ttl: timedelta = DAY, secret: str | None = None) -> str:
    return encode_token(user_id, secret or settings().jwt_secret.get_secret_value(), ttl)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def login(client: httpx.AsyncClient, clock: ModuleType, **kwargs: Any) -> httpx.Response:
    raw = make_init_data(auth_date=kwargs.pop("auth_date", clock.now()), **kwargs)
    return await client.post("/api/auth/telegram", json={"init_data": raw})


# --- POST /api/auth/telegram ------------------------------------------------------------------


async def test_login_upserts_user_and_returns_jwt(
    client_: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    resp = await login(
        client_,
        frozen_clock,
        user={
            "id": 5001,
            "first_name": "Alice",
            "last_name": "Liddell",
            "username": "alice",
            "photo_url": "https://t.me/i/userpic/320/a.jpg",
        },
        extra={"start_param": "invite_xyz"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["cache-control"] == "no-store"
    body = resp.json()
    assert set(body) >= {"jwt", "user", "start_param"}
    assert body["start_param"] == "invite_xyz"
    assert body["user"]["tg_user_id"] == 5001
    assert body["user"]["display_name"] == "Alice Liddell"
    assert body["user"]["tg_username"] == "alice"
    assert body["user"]["avatar_url"] == "https://t.me/i/userpic/320/a.jpg"
    assert body["user"]["locale"] == "en"
    claims = pyjwt.decode(body["jwt"], options={"verify_signature": False})
    assert claims["sub"] == str(body["user"]["id"])
    assert claims["exp"] - claims["iat"] == 24 * 3600

    user = await session.scalar(select(User).where(User.tg_user_id == 5001))
    assert user is not None and user.id == body["user"]["id"]


@pytest.mark.parametrize(
    ("language_code", "locale"),
    [
        ("uk", Locale.UK),
        ("UK", Locale.UK),
        ("uk-UA", Locale.UK),
        ("en", Locale.EN),
        ("ru", Locale.EN),
        (None, Locale.EN),
    ],
)
async def test_locale_defaults_from_language_code(
    client_: httpx.AsyncClient,
    session: AsyncSession,
    frozen_clock: ModuleType,
    language_code: str | None,
    locale: Locale,
) -> None:
    resp = await login(client_, frozen_clock, user={"id": 5002, "language_code": language_code})
    assert resp.status_code == 200
    assert resp.json()["user"]["locale"] == locale.value
    user = await session.scalar(select(User).where(User.tg_user_id == 5002))
    assert user is not None and user.locale == locale


async def test_relogin_updates_telegram_fields_but_keeps_user_and_locale(
    client_: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    first = await login(
        client_, frozen_clock, user={"id": 5003, "username": "old", "language_code": "uk"}
    )
    second = await login(
        client_,
        frozen_clock,
        user={"id": 5003, "first_name": "Renamed", "username": "new", "language_code": "en"},
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["user"]["id"] == second.json()["user"]["id"]
    assert second.json()["user"]["tg_username"] == "new"
    assert second.json()["user"]["display_name"] == "Renamed"
    assert second.json()["user"]["locale"] == "uk"
    count = await session.scalar(
        select(func.count()).select_from(User).where(User.tg_user_id == 5003)
    )
    assert count == 1


async def test_non_https_photo_url_is_not_stored(
    client_: httpx.AsyncClient, frozen_clock: ModuleType
) -> None:
    resp = await login(client_, frozen_clock, user={"id": 5004, "photo_url": "javascript:alert(1)"})
    assert resp.json()["user"]["avatar_url"] is None


def _tamper(raw: str, how: str) -> str:
    fields = dict(parse_qsl(raw, keep_blank_values=True))
    if how == "tampered-hash":
        fields["hash"] = ("0" if fields["hash"][0] != "0" else "1") + fields["hash"][1:]
    elif how == "tampered-user":
        fields["user"] = fields["user"].replace("279058397", "1")
    elif how == "missing-hash":
        del fields["hash"]
    return urlencode(fields)


@pytest.mark.parametrize("how", ["tampered-hash", "tampered-user", "missing-hash"])
async def test_invalid_init_data_returns_401(
    client_: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType, how: str
) -> None:
    raw = _tamper(make_init_data(auth_date=frozen_clock.now()), how)
    resp = await client_.post("/api/auth/telegram", json={"init_data": raw})
    assert resp.status_code == 401
    assert "jwt" not in resp.json()
    assert await session.scalar(select(func.count()).select_from(User)) == 0


async def test_expired_init_data_returns_401(
    client_: httpx.AsyncClient, frozen_clock: ModuleType
) -> None:
    stale = frozen_clock.now() - DAY - timedelta(seconds=1)
    resp = await login(client_, frozen_clock, auth_date=stale)
    assert resp.status_code == 401


async def test_init_data_signed_with_another_bot_returns_401(
    client_: httpx.AsyncClient, frozen_clock: ModuleType
) -> None:
    resp = await login(client_, frozen_clock, bot_token="111:ANOTHERBOTANOTHERBOTANOTHERBOT")
    assert resp.status_code == 401


@pytest.mark.parametrize("body", [{}, {"init_data": ""}, {"init_data": "x" * 9000}])
async def test_malformed_body_returns_422(client_: httpx.AsyncClient, body: dict[str, str]) -> None:
    resp = await client_.post("/api/auth/telegram", json=body)
    assert resp.status_code == 422


async def test_deleted_account_cannot_log_in(
    client_: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    await factories.create_user(session, tg_user_id=5005, deleted_at=frozen_clock.now())
    resp = await login(client_, frozen_clock, user={"id": 5005})
    assert resp.status_code == 403
    assert "jwt" not in resp.json()


async def test_login_is_rate_limited_per_client(
    client_: httpx.AsyncClient, frozen_clock: ModuleType
) -> None:
    for _ in range(ratelimit.LOGIN_LIMIT.capacity):
        assert (await login(client_, frozen_clock)).status_code == 200
    resp = await login(client_, frozen_clock)
    assert resp.status_code == 429
    assert int(resp.headers["retry-after"]) >= 1


# --- GET /api/auth/me -------------------------------------------------------------------------


async def test_me_returns_user_character_and_partnership(
    client_: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    me = await factories.create_user(session, display_name="Me")
    companion = await factories.create_user(session, display_name="Buddy")
    partnership = await factories.create_partnership(session, me, companion)
    resp = await client_.get("/api/auth/me", headers=bearer(token_for(me.id)))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["id"] == me.id
    assert body["character"]["name"] == "Me"
    assert body["partnership"] == {
        "id": partnership.id,
        "companion": {"id": companion.id, "display_name": "Buddy", "avatar_url": None},
    }


async def test_me_after_login_has_no_character_or_partnership(
    client_: httpx.AsyncClient, frozen_clock: ModuleType
) -> None:
    token = (await login(client_, frozen_clock)).json()["jwt"]
    resp = await client_.get("/api/auth/me", headers=bearer(token))
    assert resp.status_code == 200
    assert resp.json()["user"]["display_name"] == "Alice"
    assert resp.json()["character"] is None
    assert resp.json()["partnership"] is None


async def test_me_rejects_deleted_or_unknown_user(
    client_: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    gone = await factories.create_user(session, deleted_at=frozen_clock.now())
    for user_id in (gone.id, 10**9):
        resp = await client_.get("/api/auth/me", headers=bearer(token_for(user_id)))
        assert resp.status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer " + "a" * 5000},
        {"Authorization": "bearer not-a-jwt"},
    ],
    ids=["basic", "empty-bearer", "huge", "garbage"],
)
async def test_me_rejects_malformed_authorization(
    client_: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    resp = await client_.get("/api/auth/me", headers=headers)
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


async def test_jwt_is_not_accepted_from_query_or_cookie(
    client_: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    user = await factories.create_user(session)
    token = token_for(user.id)
    assert (await client_.get("/api/auth/me", params={"token": token})).status_code == 401
    assert (await client_.get("/api/auth/me", params={"jwt": token})).status_code == 401
    client_.cookies.set("jwt", token)
    assert (await client_.get("/api/auth/me")).status_code == 401


# --- every /api route requires a JWT ----------------------------------------------------------

PUBLIC_ROUTES = {("POST", "/api/auth/telegram")}


def _api_routes() -> list[tuple[str, str]]:
    from app.main import create_app

    def flatten(routes: Any) -> Any:
        for route in routes:
            if isinstance(route, APIRoute):
                yield route.path, route.methods
            elif hasattr(route, "effective_route_contexts"):
                # FastAPI >= 0.16x keeps included routers as _IncludedRouter wrappers.
                for ctx in route.effective_route_contexts():
                    yield ctx.path, ctx.methods or set()
            elif hasattr(route, "routes"):
                yield from flatten(route.routes)

    found: list[tuple[str, str]] = []
    for path, methods in flatten(create_app().routes):
        if path.startswith("/api/"):
            for method in sorted(methods):
                if (method, path) not in PUBLIC_ROUTES:
                    found.append((method, path))
    return found


API_ROUTES = _api_routes()


def test_route_walk_covers_known_routes() -> None:
    assert ("GET", "/api/auth/me") in API_ROUTES
    assert ("POST", "/api/test/reset") in API_ROUTES


def _bad_token(kind: str, user_id: int) -> str | None:
    if kind == "none":
        return None
    if kind == "expired":
        return token_for(user_id, ttl=timedelta(seconds=-1))
    if kind == "wrong-signature":
        return token_for(user_id, secret="x" * 64)
    if kind == "alg-none":
        now = 0
        return pyjwt.encode(
            {"sub": str(user_id), "iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": 2**40},
            key="",
            algorithm="none",
        )
    raise AssertionError(kind)


@pytest.mark.parametrize("kind", ["none", "expired", "wrong-signature", "alg-none"])
@pytest.mark.parametrize(("method", "path"), API_ROUTES)
async def test_every_api_route_requires_valid_jwt(
    client_: httpx.AsyncClient,
    session: AsyncSession,
    frozen_clock: ModuleType,
    method: str,
    path: str,
    kind: str,
) -> None:
    user = await factories.create_user(session)
    url = re.sub(r"\{[^}]+\}", "1", path)
    token = _bad_token(kind, user.id)
    headers = bearer(token) if token else {}
    resp = await client_.request(method, url, headers=headers, json={})
    assert resp.status_code == 401, f"{method} {path} with {kind}: {resp.status_code}"
    # The test-only reset must not have run.
    assert await session.get(User, user.id) is not None


# --- write rate limit -------------------------------------------------------------------------


def _add_probe(app: FastAPI) -> None:
    @app.post(PROBE)
    async def probe(user: CurrentUser) -> dict[str, int]:
        return {"user": user.id}

    @app.get(PROBE)
    async def probe_read(user: CurrentUser) -> dict[str, int]:
        return {"user": user.id}


async def test_write_routes_return_429_after_30_per_minute_per_user(
    app_client: App, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    app, client = app_client
    _add_probe(app)
    alice = await factories.create_user(session)
    bob = await factories.create_user(session)
    a, b = bearer(token_for(alice.id)), bearer(token_for(bob.id))

    for i in range(30):
        resp = await client.post(PROBE, headers=a)
        assert resp.status_code == 200, f"request {i + 1}"
    limited = await client.post(PROBE, headers=a)
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "2"

    # Reads are not limited; other users have their own bucket.
    assert (await client.get(PROBE, headers=a)).status_code == 200
    assert (await client.post(PROBE, headers=b)).status_code == 200

    frozen_clock.advance(timedelta(seconds=2))
    assert (await client.post(PROBE, headers=a)).status_code == 200
    assert (await client.post(PROBE, headers=a)).status_code == 429
    frozen_clock.advance(timedelta(minutes=1))
    statuses = [(await client.post(PROBE, headers=a)).status_code for _ in range(31)]
    assert statuses.count(200) == 30 and statuses[-1] == 429


async def test_unauthenticated_writes_do_not_consume_a_bucket(
    app_client: App, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    app, client = app_client
    _add_probe(app)
    user = await factories.create_user(session)
    for _ in range(40):
        assert (await client.post(PROBE)).status_code == 401
    assert (await client.post(PROBE, headers=bearer(token_for(user.id)))).status_code == 200


# --- POST /api/test/reset ---------------------------------------------------------------------


async def test_reset_truncates_in_test_env(
    client_: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    user = await factories.create_user(session)
    other = await factories.create_user(session)
    await factories.create_partnership(session, user, other)
    ratelimit.write_limiter.hit("user:999")
    resp = await client_.post("/api/test/reset", headers=bearer(token_for(user.id)))
    assert resp.status_code == 204, resp.text
    assert await session.scalar(select(func.count()).select_from(User)) == 0
    assert len(ratelimit.write_limiter) == 0


@pytest.mark.parametrize("env", ["development", "prod"])
@pytest.mark.parametrize("authenticated", [True, False])
async def test_reset_is_404_outside_test_env(
    app_client: App,
    session: AsyncSession,
    frozen_clock: ModuleType,
    env: Literal["development", "prod"],
    authenticated: bool,
) -> None:
    app, client = app_client
    other = settings().model_copy(update={"app_env": env})
    app.dependency_overrides[get_settings] = lambda: other
    user = await factories.create_user(session)
    headers = bearer(token_for(user.id)) if authenticated else {}
    resp = await client.post("/api/test/reset", headers=headers)
    assert resp.status_code == 404
    assert await session.get(User, user.id) is not None


def test_reset_is_hidden_from_openapi() -> None:
    from app.main import create_app

    assert not any(p.startswith("/api/test") for p in create_app().openapi()["paths"])


@pytest.mark.parametrize(
    "name", ["telerpg", "telerpg_prod", "postgres", "e2e", "_e2e", "_test", "telerpg_e2e_x"]
)
def test_reset_refuses_non_disposable_database(name: str) -> None:
    from sqlalchemy.engine import make_url

    with pytest.raises(UnsafeDatabaseError):
        test_support._assert_disposable(make_url(f"postgresql+asyncpg://u@h/{name}"))


@pytest.mark.parametrize("name", ["telerpg_e2e", "telerpg_test"])
def test_reset_accepts_disposable_database(name: str) -> None:
    from sqlalchemy.engine import make_url

    test_support._assert_disposable(make_url(f"postgresql+asyncpg://u@h/{name}"))


async def test_reset_returns_500_on_non_disposable_database(
    client_: httpx.AsyncClient,
    session: AsyncSession,
    frozen_clock: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await factories.create_user(session)

    def refuse(_url: object) -> None:
        raise UnsafeDatabaseError("nope")

    monkeypatch.setattr(test_support, "_assert_disposable", refuse)
    resp = await client_.post("/api/test/reset", headers=bearer(token_for(user.id)))
    assert resp.status_code == 500
    assert await session.get(User, user.id) is not None
