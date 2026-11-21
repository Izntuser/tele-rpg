"""Shared FastAPI dependencies.

``current_user`` is the only way a route learns who is calling: it reads the
``Authorization: Bearer <jwt>`` header (never a query parameter or cookie), verifies the token
and loads the (not deleted) user. Every write request (POST/PUT/PATCH/DELETE) by that user
also takes a token from the per-user write bucket (30/min) and gets 429 when it is empty, so
write routes are rate-limited without opting in.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.ratelimit import RateLimiter, write_limiter
from app.db.session import get_session
from app.modules.auth.jwt import TokenError, decode_token
from app.modules.auth.service import get_active_user
from app.modules.users.models import User

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
MAX_TOKEN_LEN = 4096

_bearer = HTTPBearer(auto_error=False, description="JWT from POST /api/auth/telegram")

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def too_many_requests(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many requests",
        headers={"Retry-After": str(retry_after)},
    )


def enforce(limiter: RateLimiter, key: str) -> None:
    decision = limiter.hit(key)
    if not decision.allowed:
        raise too_many_requests(decision.retry_after)


async def current_user(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized()
    token = credentials.credentials
    if not token or len(token) > MAX_TOKEN_LEN:
        raise unauthorized()
    try:
        claims = decode_token(token, settings.jwt_secret.get_secret_value())
    except TokenError:
        raise unauthorized() from None
    user = await get_active_user(session, claims.user_id)
    if user is None:
        raise unauthorized()
    if request.method in WRITE_METHODS:
        enforce(write_limiter, f"user:{user.id}")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
