"""Inventory over HTTP: the voucher flow purchased -> requested -> scheduled -> fulfilled, the
48h dispute, refund rules (who, when, exactly one credit, quantity restored, frozen wallets),
authorization, and a journal event plus notification for every transition."""

from datetime import timedelta
from types import ModuleType
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock, ratelimit
from app.modules.common.enums import GoldTransactionType, RewardStatus
from app.modules.economy.models import GoldTransaction
from app.modules.rewards.models import Reward, RewardPurchase
from tests import factories
from tests.integration.completion_support import assert_ledger_invariants, auth, count
from tests.integration.reward_support import (
    Shop,
    act,
    balance,
    bought,
    create_reward,
    events,
    notifications,
    shop,
)


@pytest.fixture(autouse=True)
def _clean_limiters() -> None:
    ratelimit.reset_all()


def _later(hours: int = 24) -> str:
    return (clock.now() + timedelta(hours=hours)).isoformat()


async def _voucher(
    client: httpx.AsyncClient, session: AsyncSession, **reward: Any
) -> tuple[Shop, dict[str, Any]]:
    s = await shop(session, balance=500)
    values: dict[str, Any] = {"price": 100}
    values.update(reward)
    created = await create_reward(client, s.provider, **values)
    return s, await bought(client, s.buyer, created["id"])


async def _to(client: httpx.AsyncClient, s: Shop, voucher_id: int, target: str) -> dict[str, Any]:
    """Walk a purchased voucher forward to ``target``."""
    steps = [
        ("requested", s.buyer, "request", {}),
        ("scheduled", s.provider, "schedule", {"scheduled_for": _later()}),
        ("fulfilled", s.provider, "fulfill", {}),
    ]
    data: dict[str, Any] = {}
    for status, user_id, action, body in steps:
        r = await act(client, user_id, voucher_id, action, **body)
        assert r.status_code == 200, r.text
        data = r.json()
        if status == target:
            break
    return data


async def test_full_flow_with_journal_and_notifications(
    client: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    s, v = await _voucher(client, session)
    vid = v["id"]
    r = await act(client, s.buyer, vid, "request")
    assert r.status_code == 200 and r.json()["status"] == "requested"
    assert r.json()["requested_at"] is not None

    when = _later(48)
    r = await act(
        client, s.provider, vid, "schedule", scheduled_for=when, note="At 7, bring snacks"
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "scheduled" and data["side"] == "provider"
    assert data["schedule_note"] == "At 7, bring snacks" and data["scheduled_for"] is not None

    # Rescheduling is allowed.
    r = await act(client, s.provider, vid, "schedule", scheduled_for=_later(72))
    assert r.status_code == 200 and r.json()["schedule_note"] is None

    r = await act(client, s.provider, vid, "fulfill")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "fulfilled" and data["dispute_until"] is not None

    assert await events(session, "reward_purchase", vid) == [
        "reward_purchased",
        "reward_requested",
        "reward_scheduled",
        "reward_scheduled",
        "reward_fulfilled",
    ]
    assert await notifications(session, "reward_purchase", vid) == [
        (s.provider, "reward_purchased"),
        (s.provider, "reward_requested"),
        (s.buyer, "reward_scheduled"),
        (s.buyer, "reward_scheduled"),
        (s.buyer, "reward_fulfilled"),
    ]
    # Free text never reaches a payload.
    from app.modules.journal.models import JournalEvent

    payloads = await session.scalars(
        select(JournalEvent.payload).where(JournalEvent.entity_id == vid)
    )
    assert all("snacks" not in str(p) for p in payloads)

    # No Gold moved after the purchase.
    assert await balance(session, s.buyer, s.partnership) == 400
    assert await balance(session, s.provider, s.partnership) == 0


async def test_dispute_within_48h_returns_to_requested(
    client: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    s, v = await _voucher(client, session)
    await _to(client, s, v["id"], "fulfilled")
    frozen_clock.advance(timedelta(hours=47))
    r = await act(client, s.buyer, v["id"], "dispute")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "requested" and data["disputed_at"] is not None
    assert data["fulfilled_at"] is None and data["scheduled_for"] is None
    assert (await events(session, "reward_purchase", v["id"]))[-1] == "reward_disputed"
    assert (await notifications(session, "reward_purchase", v["id"]))[-1] == (
        s.provider,
        "reward_disputed",
    )
    assert await balance(session, s.buyer, s.partnership) == 400
    # Back in the flow: the provider can schedule again, or refund.
    r = await act(client, s.provider, v["id"], "refund")
    assert r.status_code == 200 and r.json()["status"] == "refunded"
    assert await balance(session, s.buyer, s.partnership) == 500


async def test_dispute_after_48h_is_refused(
    client: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    s, v = await _voucher(client, session)
    await _to(client, s, v["id"], "fulfilled")
    frozen_clock.advance(timedelta(hours=48, seconds=1))
    r = await act(client, s.buyer, v["id"], "dispute")
    assert r.status_code == 409
    assert (await events(session, "reward_purchase", v["id"]))[-1] == "reward_fulfilled"


@pytest.mark.parametrize(
    ("action", "who"),
    [
        ("request", "provider"),
        ("schedule", "buyer"),
        ("fulfill", "buyer"),
        ("dispute", "provider"),
    ],
)
async def test_wrong_actor_gets_403(
    client: httpx.AsyncClient, session: AsyncSession, action: str, who: str
) -> None:
    s, v = await _voucher(client, session)
    user_id = s.provider if who == "provider" else s.buyer
    body = {"scheduled_for": _later()} if action == "schedule" else {}
    r = await act(client, user_id, v["id"], action, **body)
    assert r.status_code == 403


@pytest.mark.parametrize(
    ("status", "action", "who"),
    [
        ("purchased", "schedule", "provider"),
        ("purchased", "fulfill", "provider"),
        ("purchased", "dispute", "buyer"),
        ("requested", "request", "buyer"),
        ("requested", "fulfill", "provider"),
        ("scheduled", "request", "buyer"),
        ("fulfilled", "schedule", "provider"),
        ("fulfilled", "fulfill", "provider"),
    ],
)
async def test_wrong_status_gets_409(
    client: httpx.AsyncClient, session: AsyncSession, status: str, action: str, who: str
) -> None:
    s, v = await _voucher(client, session)
    if status != "purchased":
        await _to(client, s, v["id"], status)
    user_id = s.provider if who == "provider" else s.buyer
    body = {"scheduled_for": _later()} if action == "schedule" else {}
    r = await act(client, user_id, v["id"], action, **body)
    assert r.status_code == 409, r.text


async def test_schedule_validation(client: httpx.AsyncClient, session: AsyncSession) -> None:
    s, v = await _voucher(client, session)
    await _to(client, s, v["id"], "requested")
    past = (clock.now() - timedelta(minutes=1)).isoformat()
    assert (
        await act(client, s.provider, v["id"], "schedule", scheduled_for=past)
    ).status_code == 409
    naive = (clock.now() + timedelta(days=1)).replace(tzinfo=None).isoformat()
    assert (
        await act(client, s.provider, v["id"], "schedule", scheduled_for=naive)
    ).status_code == 422
    assert (await act(client, s.provider, v["id"], "schedule")).status_code == 422
    assert (
        await act(client, s.provider, v["id"], "schedule", scheduled_for=_later(), note="x" * 501)
    ).status_code == 422


async def test_strangers_get_404(client: httpx.AsyncClient, session: AsyncSession) -> None:
    s, v = await _voucher(client, session)
    stranger = await factories.create_user(session)
    stranger_id = stranger.id
    await session.commit()
    for action in ("request", "fulfill", "dispute", "refund"):
        assert (await act(client, stranger_id, v["id"], action)).status_code == 404
    assert (await act(client, s.buyer, 10**12, "request")).status_code == 404
    assert (await client.get("/api/inventory", headers=auth(stranger_id))).json() == []


# --- refunds ---------------------------------------------------------------------------------


async def _refund_ledger(session: AsyncSession, purchase_id: int) -> list[GoldTransaction]:
    rows = await session.scalars(
        select(GoldTransaction).where(
            GoldTransaction.purchase_id == purchase_id,
            GoldTransaction.type == GoldTransactionType.REWARD_REFUND,
        )
    )
    return list(rows)


@pytest.mark.parametrize("status", ["purchased", "requested", "scheduled"])
async def test_provider_refunds_before_fulfilment(
    client: httpx.AsyncClient, session: AsyncSession, status: str
) -> None:
    s, v = await _voucher(client, session, quantity_limit=1)
    if status != "purchased":
        await _to(client, s, v["id"], status)
    r = await act(client, s.provider, v["id"], "refund")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "refunded" and data["refunded_by"] == s.provider
    [credit] = await _refund_ledger(session, v["id"])
    assert credit.amount == 100 and credit.idempotency_key == f"refund:{v['id']}"
    assert credit.user_id == s.buyer
    assert await balance(session, s.buyer, s.partnership) == 500
    reward = await session.get(Reward, v["reward_id"], populate_existing=True)
    assert reward is not None
    assert reward.quantity_remaining == 1 and reward.status == RewardStatus.ACTIVE
    assert (await events(session, "reward_purchase", v["id"]))[-1] == "reward_refunded"
    assert (await notifications(session, "reward_purchase", v["id"]))[-1] == (
        s.buyer,
        "reward_refunded",
    )
    await assert_ledger_invariants(session)


async def test_nobody_refunds_a_fulfilled_voucher(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    s, v = await _voucher(client, session)
    await _to(client, s, v["id"], "fulfilled")
    assert (await act(client, s.provider, v["id"], "refund")).status_code == 409
    assert (await act(client, s.buyer, v["id"], "refund")).status_code == 409
    assert await _refund_ledger(session, v["id"]) == []


async def test_buyer_refunds_only_while_purchased(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    s, v = await _voucher(client, session)
    await _to(client, s, v["id"], "requested")
    assert (await act(client, s.buyer, v["id"], "refund")).status_code == 409

    s2, v2 = await _voucher(client, session)
    r = await act(client, s2.buyer, v2["id"], "refund")
    assert r.status_code == 200 and r.json()["refunded_by"] == s2.buyer
    assert (await notifications(session, "reward_purchase", v2["id"]))[-1] == (
        s2.provider,
        "reward_refunded",
    )


async def test_refund_happens_once(client: httpx.AsyncClient, session: AsyncSession) -> None:
    s, v = await _voucher(client, session, quantity_limit=3)
    assert (await act(client, s.provider, v["id"], "refund")).status_code == 200
    assert (await act(client, s.provider, v["id"], "refund")).status_code == 409
    assert (await act(client, s.buyer, v["id"], "refund")).status_code == 409
    assert len(await _refund_ledger(session, v["id"])) == 1
    reward = await session.get(Reward, v["reward_id"], populate_existing=True)
    assert reward is not None and reward.quantity_remaining == 3
    assert await balance(session, s.buyer, s.partnership) == 500


async def test_refund_to_a_frozen_wallet_still_credits_it(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    s, v = await _voucher(client, session)
    r = await client.post(
        "/api/partnership/leave", json={"confirm_text": "LEAVE"}, headers=auth(s.provider)
    )
    assert r.status_code in (200, 204)
    # Only a refund still works on an ended partnership.
    assert (await act(client, s.buyer, v["id"], "request")).status_code == 409
    r = await act(client, s.buyer, v["id"], "refund")
    assert r.status_code == 200, r.text
    assert r.json()["frozen"] is True
    assert await balance(session, s.buyer, s.partnership) == 500
    frozen = (await client.get("/api/economy/balance", headers=auth(s.buyer))).json()
    assert frozen["active"] is None and frozen["frozen"][0]["balance"] == 500
    await assert_ledger_invariants(session)


@pytest.mark.parametrize("action", ["request", "schedule", "fulfill", "dispute"])
async def test_transitions_other_than_refund_need_an_active_partnership(
    client: httpx.AsyncClient, session: AsyncSession, action: str
) -> None:
    s, v = await _voucher(client, session)
    prior = {"request": None, "schedule": "requested", "fulfill": "scheduled"}.get(
        action, "fulfilled"
    )
    if prior is not None:
        await _to(client, s, v["id"], prior)
    r = await client.post(
        "/api/partnership/leave", json={"confirm_text": "LEAVE"}, headers=auth(s.buyer)
    )
    assert r.status_code in (200, 204)
    user_id = s.buyer if action in ("request", "dispute") else s.provider
    body = {"scheduled_for": _later()} if action == "schedule" else {}
    assert (await act(client, user_id, v["id"], action, **body)).status_code == 409


# --- lists -----------------------------------------------------------------------------------


async def test_inventory_lists_by_side_and_status(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    s = await shop(session, balance=500)
    reward = await create_reward(client, s.provider, price=10)
    first = await bought(client, s.buyer, reward["id"])
    second = await bought(client, s.buyer, reward["id"])
    await _to(client, s, second["id"], "requested")

    mine = (await client.get("/api/inventory?side=buyer", headers=auth(s.buyer))).json()
    assert [v["id"] for v in mine] == [second["id"], first["id"]]
    assert all(v["side"] == "buyer" for v in mine)
    to_provide = (await client.get("/api/inventory?side=provider", headers=auth(s.provider))).json()
    assert [v["id"] for v in to_provide] == [second["id"], first["id"]]
    assert all(v["side"] == "provider" for v in to_provide)
    assert (await client.get("/api/inventory?side=provider", headers=auth(s.buyer))).json() == []
    requested = (
        await client.get("/api/inventory?status=requested&status=scheduled", headers=auth(s.buyer))
    ).json()
    assert [v["id"] for v in requested] == [second["id"]]


async def test_provider_deletion_scrubs_the_schedule_note(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    s, v = await _voucher(client, session)
    await _to(client, s, v["id"], "requested")
    r = await act(
        client, s.provider, v["id"], "schedule", scheduled_for=_later(), note="My address is..."
    )
    assert r.status_code == 200
    r = await client.request(
        "DELETE", "/api/account", json={"confirm_text": "DELETE"}, headers=auth(s.provider)
    )
    assert r.status_code in (200, 204), r.text
    row = await session.get(RewardPurchase, v["id"], populate_existing=True)
    assert row is not None and row.schedule_note is None
    # Only the provider may refund a scheduled voucher, and the provider is gone: the voucher
    # stays as it is (docs/TODO.md: auto-refund open vouchers on deletion).
    assert (await act(client, s.buyer, v["id"], "refund")).status_code == 409
    assert await count(session, GoldTransaction, GoldTransaction.purchase_id == v["id"]) == 1
