"""My account: JSON export and deletion. Both act on the caller only."""

from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import JSONResponse

from app.api.routes.files import StorageDep
from app.core.deps import CurrentUser, SessionDep
from app.modules.partnerships.schemas import ConfirmIn
from app.modules.users import account

router = APIRouter(prefix="/account", tags=["account"])


@router.get("/export", response_model=dict[str, Any])
async def export_account(user: CurrentUser, session: SessionDep) -> JSONResponse:
    """Everything stored about me, as one JSON document (downloaded as a file)."""
    data = await account.export(session, user)
    return JSONResponse(
        data,
        headers={
            "Content-Disposition": 'attachment; filename="tele-rpg-export.json"',
            "Cache-Control": "no-store",
        },
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    body: ConfirmIn, user: CurrentUser, session: SessionDep, storage: StorageDep
) -> Response:
    """Typed confirmation ``DELETE``. Afterwards every existing JWT of this account is rejected
    and logging in again with the same Telegram account starts a new, empty account."""
    try:
        await account.delete_account(session, user, body.confirm_text, storage)
    except account.WrongConfirmationError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Confirmation text mismatch") from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
