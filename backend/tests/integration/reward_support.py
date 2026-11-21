"""Shared setup for the S10 shop / inventory tests (not collected: no ``test_`` prefix)."""

import itertools
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.modules.common.enums import RewardStatus
from app.modules.economy.models import Wallet
from app.modules.journal.models import JournalEvent
from app.modules.notifications.models import Notification
from app.modules.rewards.models import Reward, RewardPurchase
from app.modules.rewards.service import VOID_STATUSES
from tests import factories
from tests.integration.completion_support import auth, count

_keys = itertools.count(1)


@dataclass(frozen=True, slots=True)
class Shop:
    """``provider`` runs the shop, ``buyer`` (with ``balance`` Gold) buys from it."""

    provider: int
    buyer: int
    partnership: int


async def shop(session: AsyncSession, *, balance: int = 500) -> Shop:
    provider = await factories.create_user(session, onboarded_at=clock.now())
    buyer = await factories.create_user(session, onboarded_at=clock.now())
    partnership = await factories.create_partnership(session, provider, buyer)
    await factories.create_wallet(session, provider, partnership)
    await factories.create_wallet(session, buyer, partnership, balance=balance)
    out = Shop(provider.id, buyer.id, partnership.id)
    await session.commit()
    return out


def key() -> str:
    return f"key-{next(_keys)}"


async def create_reward(client: httpx.AsyncClient, user_id: int, **body: Any) -> dict[str, Any]:
    values: dict[str, Any] = {"title": "Movie night", "price": 100}
    values.update(body)
    r = await client.post("/api/rewards", json=values, headers=auth(user_id))
    assert r.status_code == 201, r.text
    data: dict[str, Any] = r.json()
    return data


async def buy(
    client: httpx.AsyncClient, user_id: int, reward_id: int, idem: str | None = None
) -> httpx.Response:
    return await client.post(
        f"/api/rewards/{reward_id}/purchase",
        headers=auth(user_id, **{"Idempotency-Key": idem or key()}),
    )


async def bought(client: httpx.AsyncClient, user_id: int, reward_id: int) -> dict[str, Any]:
    r = await buy(client, user_id, reward_id)
    assert r.status_code == 201, r.text
    data: dict[str, Any] = r.json()
    return data


async def act(
    client: httpx.AsyncClient, user_id: int, purchase_id: int, action: str, **body: Any
) -> httpx.Response:
    return await client.post(
        f"/api/inventory/{purchase_id}/{action}", json=body or None, headers=auth(user_id)
    )


async def events(session: AsyncSession, entity_type: str, entity_id: int) -> list[str]:
    rows = await session.scalars(
        select(JournalEvent.type)
        .where(JournalEvent.entity_type == entity_type, JournalEvent.entity_id == entity_id)
        .order_by(JournalEvent.id)
    )
    return list(rows)


async def notifications(
    session: AsyncSession, entity_type: str, entity_id: int
) -> list[tuple[int, str]]:
    rows = await session.execute(
        select(Notification.recipient_id, Notification.type)
        .where(Notification.entity_type == entity_type, Notification.entity_id == entity_id)
        .order_by(Notification.id)
    )
    return [(r[0], r[1]) for r in rows.all()]


async def balance(session: AsyncSession, user_id: int, partnership_id: int) -> int:
    value = await session.scalar(
        select(Wallet.balance)
        .where(Wallet.user_id == user_id, Wallet.partnership_id == partnership_id)
        .execution_options(populate_existing=True)
    )
    assert value is not None
    return value


async def assert_quantity_consistent(s: AsyncSession, reward_id: int) -> None:
    """``quantity_remaining == max(0, quantity_limit - live purchases)``; none left means
    ``sold_out`` (unless hidden). A limit lowered below the units sold leaves 0, never more."""
    reward = await s.get(Reward, reward_id, populate_existing=True)
    assert reward is not None
    live = await count(
        s,
        RewardPurchase,
        RewardPurchase.reward_id == reward_id,
        RewardPurchase.status.not_in(VOID_STATUSES),
    )
    if reward.quantity_limit is not None:
        assert reward.quantity_remaining == max(0, reward.quantity_limit - live)
        if reward.status != RewardStatus.HIDDEN:
            expected = (
                RewardStatus.SOLD_OUT if reward.quantity_remaining == 0 else RewardStatus.ACTIVE
            )
            assert reward.status == expected
