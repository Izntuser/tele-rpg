"""Stats and Life Balance (ARCHITECTURE §5 "stats"). Life Balance may be read for the active
companion (``?user=companion``); targets are only ever my own."""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status

from app.core.deps import CurrentUser, SessionDep
from app.modules.stats import service
from app.modules.stats.service import (
    BalancePeriod,
    LifeBalanceOut,
    Period,
    StatsOut,
    TargetsIn,
    TargetsOut,
)
from app.modules.users.models import User
from app.modules.users.service import NotPartneredError, resolve_owner

router = APIRouter(prefix="/stats", tags=["stats"])

Who = Annotated[Literal["me", "companion"], Query(alias="user")]


@router.get("", response_model=StatsOut)
async def get_stats(user: CurrentUser, session: SessionDep, period: Period = "7d") -> StatsOut:
    """My counts, XP and quests per day, Gold earned/spent and rewards for the period."""
    return await service.stats(session, user, period)


@router.get("/life-balance", response_model=LifeBalanceOut)
async def get_life_balance(
    user: CurrentUser, session: SessionDep, period: BalancePeriod = "7d", who: Who = "me"
) -> LifeBalanceOut:
    """Per-attribute activity scores against the owner's targets, with suggestions (403 for
    ``user=companion`` without an active partnership)."""
    try:
        owner_id = await resolve_owner(session, user, who)
    except NotPartneredError:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No active partnership") from None
    owner = user if owner_id == user.id else await session.get(User, owner_id)
    assert owner is not None
    return await service.life_balance(session, owner, period, who)


@router.get("/life-balance/targets", response_model=TargetsOut)
async def get_targets(user: CurrentUser, session: SessionDep) -> TargetsOut:
    return TargetsOut(targets=await service.weekly_targets(session, user.id))


@router.put("/life-balance/targets", response_model=TargetsOut)
async def put_targets(body: TargetsIn, user: CurrentUser, session: SessionDep) -> TargetsOut:
    """Set my weekly XP targets (0-10000 per attribute); omitted attributes are unchanged."""
    return await service.set_targets(session, user, body)
