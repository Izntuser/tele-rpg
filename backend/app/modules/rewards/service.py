"""Reward shop: create (optionally from a companion's wishlist item), edit, list and purchase
(ARCHITECTURE §4 "Purchase", DECISIONS #16, #17).

Rules kept here:

- a reward belongs to one partnership and its creator (the provider); only the two members of
  that partnership ever see it, anyone else gets ``RewardNotFoundError`` (404);
- the creator manages it (403 for the companion); writes need the partnership to be active
  (409), so a reward is never edited while ``hidden_by_partnership_end`` is set;
- a purchase is one transaction: the buyer's wallet is debited through
  ``economy.service.post`` with ledger key ``purchase:{buyer_id}:{Idempotency-Key}``, the
  quantity is decremented (``sold_out`` at 0) and the reward is snapshotted on the purchase.
  Refused with 409: insufficient Gold, sold out, hidden, within cooldown, ended partnership
  (frozen wallet), buyer = creator;
- ``PATCH`` affects only future purchases: a purchase reads price and terms from its own
  snapshot, never from the reward;
- every purchase and voucher transition writes a journal event and a notification in the same
  transaction (``voucher_event``); payloads carry ids, the title and amounts, never free text
  typed about a person or a name.

Lock order (extends DECISIONS #16): ``idempotency_key`` claim (purchase) -> (create only) the
creator's user row ``FOR NO KEY UPDATE`` -> partnership ``FOR SHARE`` -> wishlist item / reward
``FOR UPDATE`` -> purchase ``FOR UPDATE`` -> wallet ``FOR UPDATE`` (inside ``economy.post``).
``leave`` / account deletion lock the user rows, then the partnership ``FOR UPDATE``, so they
serialize with every shop write on the partnership row and never deadlock with it.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.idempotency import Claim
from app.modules.common.enums import (
    GoldTransactionType,
    NotificationCategory,
    PartnershipStatus,
    RewardPurchaseStatus,
    RewardStatus,
    WishlistStatus,
)
from app.modules.economy import service as economy
from app.modules.journal.service import record_event
from app.modules.notifications.service import enqueue
from app.modules.partnerships.models import Partnership
from app.modules.partnerships.service import companion_of, find_active
from app.modules.rewards import state
from app.modules.rewards.models import Reward, RewardPurchase
from app.modules.rewards.schemas import (
    LIST_LIMIT_MAX,
    MAX_REWARDS,
    PurchaseOut,
    PurchaseResult,
    RewardCreate,
    RewardOut,
    RewardSnapshot,
    RewardUpdate,
    Shop,
    Side,
)
from app.modules.users.models import User
from app.modules.users.service import lock_user
from app.modules.wishlist.models import WishlistItem

#: Purchases that no longer count against the quantity or the cooldown.
VOID_STATUSES = (RewardPurchaseStatus.REFUNDED, RewardPurchaseStatus.CANCELLED)


class RewardError(Exception):
    message = "Reward error"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)
        if message is not None:
            self.message = message


class RewardNotFoundError(RewardError):
    message = "Reward not found"


class VoucherNotFoundError(RewardError):
    message = "Voucher not found"


class NotPartneredError(RewardError):
    message = "No active partnership"


class WrongRoleError(RewardError):
    message = "Not allowed for your role"


class InvalidWishlistItemError(RewardError):
    message = "wishlist_item_id must be an item on your companion's wishlist"


class RewardConflictError(RewardError):
    """Any 409: the request is valid but the current state refuses it."""

    message = "Conflict"


class PartnershipInactiveError(RewardConflictError):
    message = "Partnership has ended"


class TooManyRewardsError(RewardConflictError):
    message = "Too many rewards in your shop"


class WishlistItemTakenError(RewardConflictError):
    message = "This wishlist item is already offered or archived"


class OwnRewardError(RewardConflictError):
    message = "You cannot buy your own reward"


class RewardHiddenError(RewardConflictError):
    message = "This reward is not available"


class SoldOutError(RewardConflictError):
    message = "This reward is sold out"


class CooldownError(RewardConflictError):
    message = "This reward is on cooldown"


class InsufficientGoldError(RewardConflictError):
    message = "Not enough gold"


class PurchaseKeyUsedError(RewardConflictError):
    message = "This Idempotency-Key was already used for a purchase"


class VoucherStateError(RewardConflictError):
    message = "Voucher state does not allow this"


# --- shared helpers --------------------------------------------------------------------------


async def lock_partnership(session: AsyncSession, partnership_id: int) -> Partnership:
    """The partnership row ``FOR SHARE``, re-read from the database (any status)."""
    partnership = await session.scalar(
        select(Partnership)
        .where(Partnership.id == partnership_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    assert partnership is not None
    return partnership


def is_member(partnership: Partnership, user_id: int) -> bool:
    return user_id in (partnership.user_a_id, partnership.user_b_id)


def voucher_event(
    session: AsyncSession,
    *,
    actor_id: int,
    recipient_id: int,
    type_: str,
    purchase: RewardPurchase,
    extra: dict[str, Any] | None = None,
) -> None:
    """Journal event (shared, by the actor) + notification to the other member."""
    snapshot = RewardSnapshot.model_validate(purchase.reward_snapshot)
    payload: dict[str, Any] = {
        "purchase_id": purchase.id,
        "reward_id": purchase.reward_id,
        "title": snapshot.title,
        "price": purchase.price_paid,
        **(extra or {}),
    }
    record_event(
        session,
        user_id=actor_id,
        type=type_,
        partnership_id=purchase.partnership_id,
        entity_type="reward_purchase",
        entity_id=purchase.id,
        payload=payload,
    )
    enqueue(
        session,
        recipient_id=recipient_id,
        type=type_,
        category=NotificationCategory.REWARDS,
        entity_type="reward_purchase",
        entity_id=purchase.id,
        payload=payload,
    )


def purchase_out(purchase: RewardPurchase, viewer_id: int, partnership: Partnership) -> PurchaseOut:
    side: Side = "buyer" if purchase.buyer_id == viewer_id else "provider"
    dispute_until = (
        purchase.fulfilled_at + state.DISPUTE_WINDOW
        if purchase.status == RewardPurchaseStatus.FULFILLED and purchase.fulfilled_at
        else None
    )
    return PurchaseOut(
        id=purchase.id,
        reward_id=purchase.reward_id,
        buyer_id=purchase.buyer_id,
        provider_id=purchase.provider_id,
        side=side,
        price_paid=purchase.price_paid,
        reward=RewardSnapshot.model_validate(purchase.reward_snapshot),
        status=purchase.status,
        scheduled_for=purchase.scheduled_for,
        schedule_note=purchase.schedule_note,
        purchased_at=purchase.purchased_at,
        requested_at=purchase.requested_at,
        scheduled_at=purchase.scheduled_at,
        fulfilled_at=purchase.fulfilled_at,
        disputed_at=purchase.disputed_at,
        refunded_at=purchase.refunded_at,
        refunded_by=purchase.refunded_by,
        frozen=partnership.status != PartnershipStatus.ACTIVE,
        dispute_until=dispute_until,
    )


async def _live_purchases(session: AsyncSession, reward_id: int) -> int:
    sold = await session.scalar(
        select(func.count())
        .select_from(RewardPurchase)
        .where(
            RewardPurchase.reward_id == reward_id,
            RewardPurchase.status.not_in(VOID_STATUSES),
        )
    )
    return sold or 0


async def restore_unit(session: AsyncSession, reward: Reward) -> None:
    """Recount a (locked) reward's remaining units after a refund: ``max(0, limit - live
    purchases)``, never ``remaining + 1``, so a limit lowered below the units sold stays
    honoured. A sold-out reward with a free unit is active again; a hidden reward stays hidden
    (re-pairing decides, ``partnerships._restore_rewards``). Call after the purchase is void."""
    if reward.quantity_limit is None:
        return
    await session.flush()
    remaining = max(0, reward.quantity_limit - await _live_purchases(session, reward.id))
    reward.quantity_remaining = remaining
    if reward.status in (RewardStatus.SOLD_OUT, RewardStatus.ACTIVE):
        reward.status = RewardStatus.SOLD_OUT if remaining <= 0 else RewardStatus.ACTIVE


def _effective_status(availability: str, remaining: int | None) -> RewardStatus:
    if availability == RewardStatus.HIDDEN.value:
        return RewardStatus.HIDDEN
    if remaining is not None and remaining <= 0:
        return RewardStatus.SOLD_OUT
    return RewardStatus.ACTIVE


def _availability(reward: Reward) -> str:
    return "hidden" if reward.status == RewardStatus.HIDDEN else "active"


async def _last_purchase_at(
    session: AsyncSession, buyer_id: int, reward_ids: Sequence[int]
) -> dict[int, datetime]:
    if not reward_ids:
        return {}
    rows = await session.execute(
        select(RewardPurchase.reward_id, func.max(RewardPurchase.purchased_at))
        .where(
            RewardPurchase.buyer_id == buyer_id,
            RewardPurchase.reward_id.in_(reward_ids),
            RewardPurchase.status.not_in(VOID_STATUSES),
        )
        .group_by(RewardPurchase.reward_id)
    )
    return {reward_id: at for reward_id, at in rows.all()}


def _cooldown_until(reward: Reward, last: datetime | None) -> datetime | None:
    if not reward.cooldown_days or last is None:
        return None
    until = last + timedelta(days=reward.cooldown_days)
    return until if until > clock.now() else None


def _reward_out(reward: Reward, viewer_id: int, last: datetime | None = None) -> RewardOut:
    mine = reward.creator_id == viewer_id
    return RewardOut(
        id=reward.id,
        creator_id=reward.creator_id,
        title=reward.title,
        description=reward.description,
        price=reward.price,
        image_file_id=reward.image_file_id,
        quantity_limit=reward.quantity_limit,
        quantity_remaining=reward.quantity_remaining,
        cooldown_days=reward.cooldown_days,
        status=reward.status,
        source_wishlist_item_id=reward.source_wishlist_item_id,
        mine=mine,
        cooldown_until=None if mine else _cooldown_until(reward, last),
        created_at=reward.created_at,
        updated_at=reward.updated_at,
    )


async def _active_partnership_locked(session: AsyncSession, user: User) -> Partnership:
    probe = await find_active(session, user.id)
    if probe is None:
        raise NotPartneredError
    partnership = await lock_partnership(session, probe.id)
    if partnership.status != PartnershipStatus.ACTIVE:
        raise NotPartneredError
    return partnership


async def _lock_reward(
    session: AsyncSession, user: User, reward_id: int
) -> tuple[Partnership, Reward]:
    """Membership check (404 otherwise), then partnership ``FOR SHARE`` and reward ``FOR
    UPDATE``, both re-read. The partnership may be ended; callers decide."""
    partnership_id = await session.scalar(
        select(Reward.partnership_id)
        .join(Partnership, Partnership.id == Reward.partnership_id)
        .where(
            Reward.id == reward_id,
            or_(Partnership.user_a_id == user.id, Partnership.user_b_id == user.id),
        )
    )
    if partnership_id is None:
        raise RewardNotFoundError
    partnership = await lock_partnership(session, partnership_id)
    reward = await session.scalar(
        select(Reward)
        .where(Reward.id == reward_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert reward is not None
    return partnership, reward


# --- shop management -------------------------------------------------------------------------


async def create(session: AsyncSession, user: User, data: RewardCreate) -> RewardOut:
    """A reward in my shop of the active partnership; from ``wishlist_item_id`` (an open item of
    my companion) the item becomes ``offered`` and linked to the new reward."""
    await lock_user(session, user.id)
    partnership = await _active_partnership_locked(session, user)
    count = await session.scalar(
        select(func.count())
        .select_from(Reward)
        .where(Reward.partnership_id == partnership.id, Reward.creator_id == user.id)
    )
    if (count or 0) >= MAX_REWARDS:
        raise TooManyRewardsError

    item: WishlistItem | None = None
    if data.wishlist_item_id is not None:
        item = await session.scalar(
            select(WishlistItem)
            .where(
                WishlistItem.id == data.wishlist_item_id,
                WishlistItem.user_id == companion_of(partnership, user.id),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if item is None:
            raise InvalidWishlistItemError
        if item.status != WishlistStatus.OPEN or item.linked_reward_id is not None:
            raise WishlistItemTakenError

    title = data.title if data.title is not None else (item.title if item else None)
    assert title is not None  # RewardCreate requires a title without a wishlist item
    description = data.description
    if item is not None and "description" not in data.model_fields_set:
        description = item.description

    reward = Reward(
        partnership_id=partnership.id,
        creator_id=user.id,
        title=title,
        description=description,
        price=data.price,
        quantity_limit=data.quantity_limit,
        quantity_remaining=data.quantity_limit,
        cooldown_days=data.cooldown_days,
        status=_effective_status(data.status, data.quantity_limit),
        hidden_by_partnership_end=False,
        source_wishlist_item_id=item.id if item else None,
    )
    session.add(reward)
    await session.flush()
    if item is not None:
        item.status = WishlistStatus.OFFERED
        item.linked_reward_id = reward.id
    payload = {
        "reward_id": reward.id,
        "title": reward.title,
        "price": reward.price,
        "from_wishlist": item is not None,
    }
    if reward.status != RewardStatus.HIDDEN:
        record_event(
            session,
            user_id=user.id,
            type="reward_created",
            partnership_id=partnership.id,
            entity_type="reward",
            entity_id=reward.id,
            payload=payload,
        )
        enqueue(
            session,
            recipient_id=companion_of(partnership, user.id),
            type="reward_created",
            category=NotificationCategory.REWARDS,
            entity_type="reward",
            entity_id=reward.id,
            payload=payload,
        )
    await session.flush()
    await session.refresh(reward)
    out = _reward_out(reward, user.id)
    await session.commit()
    return out


async def update(
    session: AsyncSession, user: User, reward_id: int, data: RewardUpdate
) -> RewardOut:
    """Creator: change price / terms / availability for future purchases. Existing purchases
    keep their snapshot. A new ``quantity_limit`` counts the purchases already made (not
    refunded) against it; null makes the reward unlimited."""
    partnership, reward = await _lock_reward(session, user, reward_id)
    if reward.creator_id != user.id:
        raise WrongRoleError
    if partnership.status != PartnershipStatus.ACTIVE:
        raise PartnershipInactiveError
    sent = data.model_fields_set
    if "title" in sent and data.title is not None:
        reward.title = data.title
    if "description" in sent:
        reward.description = data.description
    if "price" in sent and data.price is not None:
        reward.price = data.price
    if "cooldown_days" in sent:
        reward.cooldown_days = data.cooldown_days
    if "quantity_limit" in sent:
        if data.quantity_limit is None:
            reward.quantity_limit = None
            reward.quantity_remaining = None
        else:
            sold = await _live_purchases(session, reward.id)
            reward.quantity_remaining = max(0, data.quantity_limit - sold)
            reward.quantity_limit = data.quantity_limit
    availability = data.status if "status" in sent and data.status else _availability(reward)
    reward.status = _effective_status(availability, reward.quantity_remaining)
    # Any creator change ends the "hidden by the partnership end" state (DECISIONS #17).
    reward.hidden_by_partnership_end = False
    reward.updated_at = clock.now()
    await session.flush()
    await session.refresh(reward)
    last = await _last_purchase_at(session, user.id, [reward.id])
    out = _reward_out(reward, user.id, last.get(reward.id))
    await session.commit()
    return out


async def list_rewards(
    session: AsyncSession, user: User, *, shop: Shop, limit: int = LIST_LIMIT_MAX
) -> list[RewardOut]:
    """The shop of my active partnership: ``mine`` (every status) or my companion's (active and
    sold out; hidden ones are not shown). Empty without an active partnership."""
    partnership = await find_active(session, user.id)
    if partnership is None:
        return []
    creator_id = user.id if shop == "mine" else companion_of(partnership, user.id)
    query = select(Reward).where(
        Reward.partnership_id == partnership.id, Reward.creator_id == creator_id
    )
    if shop == "companion":
        query = query.where(Reward.status != RewardStatus.HIDDEN)
    rewards = list(await session.scalars(query.order_by(Reward.id).limit(limit)))
    last = (
        await _last_purchase_at(session, user.id, [r.id for r in rewards])
        if shop == "companion"
        else {}
    )
    return [_reward_out(r, user.id, last.get(r.id)) for r in rewards]


# --- purchase --------------------------------------------------------------------------------


async def purchase(
    session: AsyncSession,
    user: User,
    reward_id: int,
    *,
    client_key: str,
    idempotency: Claim | None = None,
) -> PurchaseResult:
    """Buy a companion's reward with my wallet of that partnership (one transaction)."""
    ledger_key = economy.purchase_key(user.id, client_key)
    partnership, reward = await _lock_reward(session, user, reward_id)
    if partnership.status != PartnershipStatus.ACTIVE:
        raise PartnershipInactiveError
    if reward.creator_id == user.id:
        raise OwnRewardError
    if reward.status == RewardStatus.HIDDEN:
        raise RewardHiddenError
    if reward.status == RewardStatus.SOLD_OUT or (
        reward.quantity_remaining is not None and reward.quantity_remaining <= 0
    ):
        raise SoldOutError
    if reward.cooldown_days:
        last = (await _last_purchase_at(session, user.id, [reward.id])).get(reward.id)
        if _cooldown_until(reward, last) is not None:
            raise CooldownError
    used = await session.scalar(
        select(RewardPurchase.id).where(RewardPurchase.idempotency_key == ledger_key)
    )
    if used is not None:
        # Only after the 24h replay window: the stored response is gone, the purchase is not.
        raise PurchaseKeyUsedError

    now = clock.now()
    snapshot = RewardSnapshot(
        reward_id=reward.id,
        title=reward.title,
        description=reward.description,
        price=reward.price,
        image_file_id=reward.image_file_id,
        cooldown_days=reward.cooldown_days,
        quantity_limit=reward.quantity_limit,
    )
    voucher = RewardPurchase(
        reward_id=reward.id,
        partnership_id=partnership.id,
        buyer_id=user.id,
        provider_id=reward.creator_id,
        price_paid=reward.price,
        reward_snapshot=snapshot.to_json(),
        status=RewardPurchaseStatus.PURCHASED,
        purchased_at=now,
        idempotency_key=ledger_key,
    )
    session.add(voucher)
    await session.flush()
    try:
        await economy.post(
            session,
            user_id=user.id,
            partnership_id=partnership.id,
            type=GoldTransactionType.REWARD_PURCHASE,
            amount=-reward.price,
            key=ledger_key,
            purchase_id=voucher.id,
        )
    except economy.InsufficientGoldError:
        raise InsufficientGoldError from None
    except economy.DuplicateLedgerEntryError:  # pragma: no cover - guarded by the check above
        raise PurchaseKeyUsedError from None
    if reward.quantity_remaining is not None:
        reward.quantity_remaining -= 1
        if reward.quantity_remaining == 0:
            reward.status = RewardStatus.SOLD_OUT
    await session.flush()
    voucher_event(
        session,
        actor_id=user.id,
        recipient_id=reward.creator_id,
        type_="reward_purchased",
        purchase=voucher,
    )
    await session.flush()
    await session.refresh(voucher)
    wallet = await economy.lock_wallet(session, user.id, partnership.id)
    result = PurchaseResult(
        **purchase_out(voucher, user.id, partnership).model_dump(), balance=wallet.balance
    )
    if idempotency is not None:
        await idempotency.store(session, 201, result.model_dump(mode="json"))
    await session.commit()
    return result
