import logging

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.core.deps import CurrentUser, SessionDep, SettingsDep, enforce, unauthorized
from app.core.ratelimit import login_limiter
from app.modules.auth import service
from app.modules.auth.schemas import AuthOut, MeOut, TelegramAuthIn, UserOut
from app.modules.auth.telegram import InitDataError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/telegram", response_model=AuthOut)
async def auth_telegram(
    body: TelegramAuthIn,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> AuthOut:
    """Exchange Telegram initData (sent in the JSON body, never the URL) for a JWT."""
    response.headers["Cache-Control"] = "no-store"
    client = request.client.host if request.client else "unknown"
    enforce(login_limiter, f"login:{client}")
    try:
        result = await service.login(session, body.init_data, settings)
    except InitDataError as exc:
        # The reason is a fixed string; initData, hash and token are never logged.
        log.info("telegram auth rejected: %s", exc)
        raise unauthorized() from None
    except service.AccountDeletedError:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account deleted") from None
    return AuthOut(
        jwt=result.token,
        expires_at=result.expires_at,
        user=UserOut.model_validate(result.user),
        start_param=result.start_param,
    )


@router.get("/me", response_model=MeOut)
async def auth_me(user: CurrentUser, session: SessionDep) -> MeOut:
    return await service.me(session, user)
