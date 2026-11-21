"""Inventory (voucher) routes. Thin: parse, call ``inventory.service``, map its errors."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.rewards import http_error
from app.core.deps import CurrentUser, SessionDep
from app.modules.common.enums import RewardPurchaseStatus
from app.modules.common.validation import IdPath
from app.modules.inventory import service
from app.modules.rewards.schemas import LIST_LIMIT_MAX, PurchaseOut, ScheduleIn, Side
from app.modules.rewards.service import RewardError

router = APIRouter(tags=["inventory"])


async def _run(session: AsyncSession, call: Callable[[], Awaitable[PurchaseOut]]) -> PurchaseOut:
    try:
        return await call()
    except RewardError as exc:
        await session.rollback()
        raise http_error(exc) from None


@router.get("/inventory", response_model=list[PurchaseOut])
async def list_inventory(
    user: CurrentUser,
    session: SessionDep,
    side: Side = "buyer",
    voucher_status: Annotated[list[RewardPurchaseStatus] | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=LIST_LIMIT_MAX)] = LIST_LIMIT_MAX,
) -> list[PurchaseOut]:
    """``side=buyer``: my vouchers; ``side=provider``: vouchers I must provide. Newest first,
    across all my partnerships (an ended one's are ``frozen``); ``status`` may repeat."""
    return await service.list_vouchers(
        session, user, side=side, statuses=voucher_status or [], limit=limit
    )


@router.post("/inventory/{purchase_id}/request", response_model=PurchaseOut)
async def request_voucher(
    purchase_id: IdPath, user: CurrentUser, session: SessionDep
) -> PurchaseOut:
    """Buyer: ask to redeem a purchased voucher."""
    return await _run(session, lambda: service.request(session, user, purchase_id))


@router.post("/inventory/{purchase_id}/schedule", response_model=PurchaseOut)
async def schedule_voucher(
    purchase_id: IdPath, body: ScheduleIn, user: CurrentUser, session: SessionDep
) -> PurchaseOut:
    """Provider: set or move the delivery time of a requested voucher."""
    return await _run(session, lambda: service.schedule(session, user, purchase_id, body))


@router.post("/inventory/{purchase_id}/fulfill", response_model=PurchaseOut)
async def fulfill_voucher(
    purchase_id: IdPath, user: CurrentUser, session: SessionDep
) -> PurchaseOut:
    """Provider: mark a scheduled voucher as delivered."""
    return await _run(session, lambda: service.fulfill(session, user, purchase_id))


@router.post("/inventory/{purchase_id}/dispute", response_model=PurchaseOut)
async def dispute_voucher(
    purchase_id: IdPath, user: CurrentUser, session: SessionDep
) -> PurchaseOut:
    """Buyer, within 48h of fulfilment: back to requested, no Gold change."""
    return await _run(session, lambda: service.dispute(session, user, purchase_id))


@router.post("/inventory/{purchase_id}/refund", response_model=PurchaseOut)
async def refund_voucher(
    purchase_id: IdPath, user: CurrentUser, session: SessionDep
) -> PurchaseOut:
    """Provider before fulfilment, buyer only while purchased: one credit back to the buyer's
    wallet (frozen or not) and the unit back to the reward."""
    return await _run(session, lambda: service.refund(session, user, purchase_id))
