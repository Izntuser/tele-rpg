"""Inventory: the voucher (``reward_purchase``) lifecycle after a purchase (ARCHITECTURE §4
"Refund", "Dispute", DECISIONS #17).

- ``request`` (buyer), ``schedule`` / ``fulfill`` (provider) and ``dispute`` (buyer, within
  48h of fulfilment, back to ``requested``, no Gold change) need an active partnership (409);
- ``refund``: the provider before ``fulfilled``, the buyer only while ``purchased``. It writes
  exactly one ``reward_refund`` credit with ledger key ``refund:{purchase_id}`` to the buyer's
  wallet of the purchase's partnership (a frozen wallet of an ended partnership too) and gives
  the unit back to the reward;
- every status change goes through ``rewards.state`` (403 wrong actor, 409 wrong status) and
  writes a journal event plus a notification to the other member;
- only the buyer and the provider ever see a voucher; anyone else gets 404.

Lock order: partnership ``FOR SHARE`` -> reward ``FOR UPDATE`` (refund) -> purchase ``FOR
UPDATE`` -> wallet ``FOR UPDATE`` (``economy.post``), a subset of the shop's order.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.modules.common.enums import GoldTransactionType, PartnershipStatus, RewardPurchaseStatus
from app.modules.economy import service as economy
from app.modules.partnerships.models import Partnership
from app.modules.rewards import state
from app.modules.rewards.models import Reward, RewardPurchase
from app.modules.rewards.schemas import LIST_LIMIT_MAX, PurchaseOut, ScheduleIn, Side
from app.modules.rewards.service import (
    PartnershipInactiveError,
    VoucherNotFoundError,
    VoucherStateError,
    WrongRoleError,
    lock_partnership,
    purchase_out,
    restore_unit,
    voucher_event,
)
from app.modules.users.models import User


@dataclass(slots=True)
class _Locked:
    partnership: Partnership
    purchase: RewardPurchase
    actor: state.Actor
    reward: Reward | None


async def _lock(
    session: AsyncSession, user: User, purchase_id: int, *, with_reward: bool = False
) -> _Locked:
    """Buyer/provider check (404 otherwise), then the locks in the documented order."""
    found = (
        await session.execute(
            select(RewardPurchase.partnership_id, RewardPurchase.reward_id).where(
                RewardPurchase.id == purchase_id,
                or_(RewardPurchase.buyer_id == user.id, RewardPurchase.provider_id == user.id),
            )
        )
    ).first()
    if found is None:
        raise VoucherNotFoundError
    partnership_id, reward_id = found
    partnership = await lock_partnership(session, partnership_id)
    reward: Reward | None = None
    if with_reward:
        reward = await session.scalar(
            select(Reward)
            .where(Reward.id == reward_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    purchase = await session.scalar(
        select(RewardPurchase)
        .where(RewardPurchase.id == purchase_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert purchase is not None
    actor: state.Actor = "buyer" if purchase.buyer_id == user.id else "provider"
    return _Locked(partnership, purchase, actor, reward)


def _transition(locked: _Locked, action: state.Action) -> RewardPurchaseStatus:
    purchase = locked.purchase
    try:
        return state.next_status(
            purchase.status,
            action,
            locked.actor,
            fulfilled_at=purchase.fulfilled_at,
            now=clock.now(),
        )
    except state.WrongActorError:
        raise WrongRoleError from None
    except state.VoucherTransitionError as exc:
        raise VoucherStateError(str(exc)) from None


def _other(purchase: RewardPurchase, user_id: int) -> int:
    return purchase.provider_id if purchase.buyer_id == user_id else purchase.buyer_id


async def _finish(
    session: AsyncSession,
    user: User,
    locked: _Locked,
    type_: str,
    extra: dict[str, Any] | None = None,
) -> PurchaseOut:
    purchase = locked.purchase
    voucher_event(
        session,
        actor_id=user.id,
        recipient_id=_other(purchase, user.id),
        type_=type_,
        purchase=purchase,
        extra=extra,
    )
    await session.flush()
    await session.refresh(purchase)
    out = purchase_out(purchase, user.id, locked.partnership)
    await session.commit()
    return out


async def _lock_active(
    session: AsyncSession, user: User, purchase_id: int, action: state.Action
) -> tuple[_Locked, RewardPurchaseStatus]:
    locked = await _lock(session, user, purchase_id)
    target = _transition(locked, action)
    if locked.partnership.status != PartnershipStatus.ACTIVE:
        raise PartnershipInactiveError
    return locked, target


# --- read ------------------------------------------------------------------------------------


async def list_vouchers(
    session: AsyncSession,
    user: User,
    *,
    side: Side,
    statuses: list[RewardPurchaseStatus],
    limit: int = LIST_LIMIT_MAX,
) -> list[PurchaseOut]:
    """My vouchers (``buyer``) or the ones I provide (``provider``), newest first, across all
    my partnerships (an ended one's vouchers are ``frozen``)."""
    column = RewardPurchase.buyer_id if side == "buyer" else RewardPurchase.provider_id
    query = (
        select(RewardPurchase, Partnership)
        .join(Partnership, Partnership.id == RewardPurchase.partnership_id)
        .where(column == user.id)
    )
    if statuses:
        query = query.where(RewardPurchase.status.in_(statuses))
    rows = (await session.execute(query.order_by(RewardPurchase.id.desc()).limit(limit))).all()
    return [purchase_out(p, user.id, partnership) for p, partnership in rows]


# --- transitions -----------------------------------------------------------------------------


async def request(session: AsyncSession, user: User, purchase_id: int) -> PurchaseOut:
    """Buyer: ask the provider to redeem the voucher."""
    locked, target = await _lock_active(session, user, purchase_id, "request")
    locked.purchase.status = target
    locked.purchase.requested_at = clock.now()
    return await _finish(session, user, locked, "reward_requested")


async def schedule(
    session: AsyncSession, user: User, purchase_id: int, data: ScheduleIn
) -> PurchaseOut:
    """Provider: set (or move) when the reward will be delivered. The note stays on the
    voucher, never in payloads."""
    locked, target = await _lock_active(session, user, purchase_id, "schedule")
    if data.scheduled_for <= clock.now():
        raise VoucherStateError("scheduled_for must be in the future")
    purchase = locked.purchase
    purchase.status = target
    purchase.scheduled_for = data.scheduled_for
    purchase.schedule_note = data.note
    purchase.scheduled_at = clock.now()
    return await _finish(
        session,
        user,
        locked,
        "reward_scheduled",
        {"scheduled_for": data.scheduled_for.isoformat()},
    )


async def fulfill(session: AsyncSession, user: User, purchase_id: int) -> PurchaseOut:
    """Provider: the reward was delivered."""
    locked, target = await _lock_active(session, user, purchase_id, "fulfill")
    locked.purchase.status = target
    locked.purchase.fulfilled_at = clock.now()
    return await _finish(session, user, locked, "reward_fulfilled")


async def dispute(session: AsyncSession, user: User, purchase_id: int) -> PurchaseOut:
    """Buyer, within 48h of fulfilment: it did not happen as promised. Back to ``requested``
    (the old schedule and fulfilment are cleared), no Gold change."""
    locked, target = await _lock_active(session, user, purchase_id, "dispute")
    purchase = locked.purchase
    purchase.status = target
    purchase.disputed_at = clock.now()
    purchase.requested_at = purchase.disputed_at
    purchase.scheduled_for = None
    purchase.scheduled_at = None
    purchase.schedule_note = None
    purchase.fulfilled_at = None
    return await _finish(session, user, locked, "reward_disputed")


async def refund(session: AsyncSession, user: User, purchase_id: int) -> PurchaseOut:
    """Provider before fulfilment, buyer while purchased: the price goes back to the buyer's
    wallet of this partnership (also when it is frozen) and the unit back to the reward."""
    locked = await _lock(session, user, purchase_id, with_reward=True)
    target = _transition(locked, "refund")
    purchase = locked.purchase
    try:
        await economy.post(
            session,
            user_id=purchase.buyer_id,
            partnership_id=purchase.partnership_id,
            type=GoldTransactionType.REWARD_REFUND,
            amount=purchase.price_paid,
            key=economy.refund_key(purchase.id),
            purchase_id=purchase.id,
        )
    except economy.DuplicateLedgerEntryError:  # pragma: no cover - the state machine guards it
        raise VoucherStateError("the voucher was already refunded") from None
    purchase.status = target
    purchase.refunded_at = clock.now()
    purchase.refunded_by = user.id
    if locked.reward is not None:
        await restore_unit(session, locked.reward)
    return await _finish(session, user, locked, "reward_refunded", {"by": locked.actor})
