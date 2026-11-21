"""Economy routes: my balance and my own Gold ledger (read-only; Gold only changes through
quests and the shop)."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.core.deps import CurrentUser, SessionDep
from app.modules.economy import service
from app.modules.economy.schemas import BalanceOut, LedgerPage

router = APIRouter(tags=["economy"])


@router.get("/economy/balance", response_model=BalanceOut)
async def get_balance(user: CurrentUser, session: SessionDep) -> BalanceOut:
    """The wallet of my active partnership plus frozen wallets of ended ones."""
    return await service.balance(session, user)


@router.get("/economy/transactions", response_model=LedgerPage)
async def list_transactions(
    user: CurrentUser,
    session: SessionDep,
    cursor: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=service.LEDGER_PAGE_MAX)] = 50,
) -> LedgerPage:
    """My ledger (all my wallets), newest first. Pass ``next_cursor`` for older rows."""
    try:
        return await service.transactions(session, user, cursor=cursor, limit=limit)
    except service.InvalidCursorError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid cursor") from None
