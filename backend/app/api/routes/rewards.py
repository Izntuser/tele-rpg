"""Reward shop routes. Thin: parse, call ``rewards.service``, map its errors. No path or body
ever takes a user or partnership id: the caller is the only subject."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.core import idempotency
from app.core.deps import CurrentUser, SessionDep
from app.modules.common.validation import IdPath
from app.modules.rewards import service
from app.modules.rewards.schemas import (
    LIST_LIMIT_MAX,
    PurchaseResult,
    RewardCreate,
    RewardOut,
    RewardUpdate,
    Shop,
)

router = APIRouter(tags=["rewards"])

KEY_REQUIRED_DETAIL = "Idempotency-Key header is required"
KEY_REUSED_DETAIL = "Idempotency-Key was already used for a different request"


def http_error(exc: service.RewardError) -> HTTPException:
    """The HTTP form of a shop / inventory error (shared with the inventory routes)."""
    if isinstance(exc, service.RewardConflictError):
        return HTTPException(status.HTTP_409_CONFLICT, exc.message)
    if isinstance(exc, service.RewardNotFoundError | service.VoucherNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, exc.message)
    if isinstance(exc, service.InvalidWishlistItemError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message)
    return HTTPException(status.HTTP_403_FORBIDDEN, exc.message)


@router.get("/rewards", response_model=list[RewardOut])
async def list_rewards(
    user: CurrentUser,
    session: SessionDep,
    shop: Shop = "companion",
    limit: Annotated[int, Query(ge=1, le=LIST_LIMIT_MAX)] = LIST_LIMIT_MAX,
) -> list[RewardOut]:
    """``shop=companion``: what I can buy (hidden rewards are left out); ``shop=mine``: the
    rewards I provide, every status. Empty without an active partnership."""
    return await service.list_rewards(session, user, shop=shop, limit=limit)


@router.post("/rewards", response_model=RewardOut, status_code=status.HTTP_201_CREATED)
async def create_reward(body: RewardCreate, user: CurrentUser, session: SessionDep) -> RewardOut:
    """Add a reward to my shop, optionally from an open item on my companion's wishlist."""
    try:
        return await service.create(session, user, body)
    except service.RewardError as exc:
        await session.rollback()
        raise http_error(exc) from None


@router.patch("/rewards/{reward_id}", response_model=RewardOut)
async def update_reward(
    reward_id: IdPath, body: RewardUpdate, user: CurrentUser, session: SessionDep
) -> RewardOut:
    """Creator: edit price, terms or availability; only future purchases are affected."""
    try:
        return await service.update(session, user, reward_id, body)
    except service.RewardError as exc:
        await session.rollback()
        raise http_error(exc) from None


@router.post(
    "/rewards/{reward_id}/purchase",
    response_model=PurchaseResult,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {
            "description": "Not enough gold, sold out, hidden, on cooldown, ended partnership, "
            "or my own reward"
        },
        422: {"description": "Missing or reused Idempotency-Key"},
    },
)
async def purchase_reward(
    reward_id: IdPath,
    user: CurrentUser,
    session: SessionDep,
    idempotency_key: idempotency.IdempotencyKeyHeader = None,
) -> PurchaseResult | JSONResponse:
    """Buy a companion's reward. The ``Idempotency-Key`` header is required: a retry with the
    same key replays the first response (24h) and never charges twice."""
    if idempotency_key is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, KEY_REQUIRED_DETAIL)
    try:
        claim = await idempotency.claim(
            session,
            user_id=user.id,
            key=idempotency_key,
            endpoint=f"rewards/{reward_id}/purchase",
            request_hash=idempotency.fingerprint({}),
        )
    except idempotency.IdempotencyKeyReusedError:
        await session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, KEY_REUSED_DETAIL) from None
    if isinstance(claim, idempotency.Replay):
        return claim.response()
    try:
        return await service.purchase(
            session, user, reward_id, client_key=idempotency_key, idempotency=claim
        )
    except service.RewardError as exc:
        await session.rollback()
        raise http_error(exc) from None
