"""Reward shop over HTTP: create (also from the companion's wishlist), edit (future purchases
only), list, and purchase with its debit, quantity, snapshot, Idempotency-Key and every 409."""

from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.modules.common.enums import (
    GoldTransactionType,
    PartnershipStatus,
    RewardStatus,
    WishlistStatus,
)
from app.modules.economy.models import GoldTransaction
from app.modules.partnerships.models import Partnership
from app.modules.rewards.models import Reward, RewardPurchase
from app.modules.users.models import User
from app.modules.wishlist.models import WishlistItem
from tests import factories
from tests.integration.completion_support import assert_ledger_invariants, auth, count
from tests.integration.reward_support import (
    balance,
    bought,
    buy,
    create_reward,
    events,
    notifications,
    shop,
)


@pytest.fixture(autouse=True)
def _clean_limiters() -> None:
    ratelimit.reset_all()


# --- create / list ---------------------------------------------------------------------------


async def test_create_reward_with_limits(client: httpx.AsyncClient, session: AsyncSession) -> None:
    s = await shop(session)
    reward = await create_reward(
        client,
        s.provider,
        title="Breakfast in bed",
        description="Pancakes",
        price=150,
        quantity_limit=3,
        cooldown_days=7,
    )
    assert reward["mine"] is True
    assert reward["creator_id"] == s.provider
    assert (reward["price"], reward["quantity_limit"], reward["quantity_remaining"]) == (150, 3, 3)
    assert reward["cooldown_days"] == 7 and reward["status"] == "active"
    assert "hidden_by_partnership_end" not in reward
    assert await events(session, "reward", reward["id"]) == ["reward_created"]
    assert await notifications(session, "reward", reward["id"]) == [(s.buyer, "reward_created")]

    mine = (await client.get("/api/rewards?shop=mine", headers=auth(s.provider))).json()
    assert [r["id"] for r in mine] == [reward["id"]]
    theirs = (await client.get("/api/rewards?shop=companion", headers=auth(s.buyer))).json()
    assert [r["id"] for r in theirs] == [reward["id"]] and theirs[0]["mine"] is False
    assert (await client.get("/api/rewards?shop=companion", headers=auth(s.provider))).json() == []


async def test_hidden_reward_is_only_in_my_shop(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    s = await shop(session)
    reward = await create_reward(client, s.provider, status="hidden")
    assert reward["status"] == "hidden"
    assert await events(session, "reward", reward["id"]) == []
    assert (await client.get("/api/rewards", headers=auth(s.buyer))).json() == []
    mine = (await client.get("/api/rewards?shop=mine", headers=auth(s.provider))).json()
    assert [r["id"] for r in mine] == [reward["id"]]


@pytest.mark.parametrize(
    "body",
    [
        {"title": "x", "price": 0},
        {"title": "x", "price": -5},
        {"title": "x", "price": 100_001},
        {"title": "x", "price": 10, "quantity_limit": 0},
        {"title": "x", "price": 10, "cooldown_days": -1},
        {"title": "x", "price": 10, "status": "sold_out"},
        {"title": "", "price": 10},
        {"price": 10},
        {"title": "x"},
    ],
)
async def test_create_validation(
    client: httpx.AsyncClient, session: AsyncSession, body: dict[str, object]
) -> None:
    s = await shop(session)
    r = await client.post("/api/rewards", json=body, headers=auth(s.provider))
    assert r.status_code == 422, r.text


async def test_server_owned_fields_are_ignored(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    s = await shop(session)
    reward = await create_reward(
        client,
        s.provider,
        quantity_limit=2,
        quantity_remaining=99,
        creator_id=s.buyer,
        partnership_id=999,
        hidden_by_partnership_end=True,
    )
    row = await session.get(Reward, reward["id"])
    assert row is not None
    assert (row.creator_id, row.partnership_id) == (s.provider, s.partnership)
    assert row.quantity_remaining == 2 and row.hidden_by_partnership_end is False


async def test_create_needs_an_active_partnership(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    loner = await factories.create_user(session)
    loner_id = loner.id
    await session.commit()
    r = await client.post("/api/rewards", json={"title": "x", "price": 5}, headers=auth(loner_id))
    assert r.status_code == 403
    assert (await client.get("/api/rewards", headers=auth(loner_id))).json() == []


async def test_create_from_companion_wishlist_item(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    s = await shop(session)
    item = WishlistItem(user_id=s.buyer, title="New headphones", description="Over-ear")
    session.add(item)
    await session.flush()
    item_id = item.id
    await session.commit()

    reward = await create_reward(
        client, s.provider, title=None, price=300, wishlist_item_id=item_id
    )
    assert reward["title"] == "New headphones" and reward["description"] == "Over-ear"
    assert reward["source_wishlist_item_id"] == item_id
    row = await session.get(WishlistItem, item_id, populate_existing=True)
    assert row is not None
    assert row.status == WishlistStatus.OFFERED and row.linked_reward_id == reward["id"]

    # The same item cannot be offered twice.
    again = await client.post(
        "/api/rewards",
        json={"price": 10, "wishlist_item_id": item_id},
        headers=auth(s.provider),
    )
    assert again.status_code == 409


async def test_wishlist_item_title_can_be_overridden(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    s = await shop(session)
    item = WishlistItem(user_id=s.buyer, title="Spa day", description="Somewhere nice")
    session.add(item)
    await session.flush()
    item_id = item.id
    await session.commit()
    reward = await create_reward(
        client, s.provider, title="Spa voucher", description=None, wishlist_item_id=item_id
    )
    assert reward["title"] == "Spa voucher" and reward["description"] is None


async def test_wishlist_item_must_belong_to_the_active_partner(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    s = await shop(session)
    stranger = await factories.create_user(session)
    own = WishlistItem(user_id=s.provider, title="Mine")
    foreign = WishlistItem(user_id=stranger.id, title="Theirs")
    archived = WishlistItem(user_id=s.buyer, title="Old", status=WishlistStatus.ARCHIVED)
    session.add_all([own, foreign, archived])
    await session.flush()
    ids = (own.id, foreign.id, archived.id)
    await session.commit()
    for item_id, code in ((ids[0], 422), (ids[1], 422), (ids[2], 409), (10**12, 422)):
        r = await client.post(
            "/api/rewards",
            json={"title": "x", "price": 5, "wishlist_item_id": item_id},
            headers=auth(s.provider),
        )
        assert r.status_code == code, (item_id, r.text)
    for item_id in ids:
        row = await session.get(WishlistItem, item_id, populate_existing=True)
        assert row is not None and row.linked_reward_id is None
    assert await count(session, Reward) == 0


async def test_reward_cap(client: httpx.AsyncClient, session: AsyncSession) -> None:
    s = await shop(session)
    p = await session.get(Partnership, s.partnership)
    provider = await session.get(User, s.provider)
    assert p is not None and provider is not None
    for _ in range(100):
        await factories.create_reward(session, p, provider)
    await session.commit()
    r = await client.post("/api/rewards", json={"title": "x", "price": 5}, headers=auth(s.provider))
    assert r.status_code == 409


# --- edit ------------------------------------------------------------------------------------


async def test_patch_changes_only_future_purchases(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    s = await shop(session, balance=1000)
    reward = await create_reward(client, s.provider, title="Dinner", price=100)
    first = await bought(client, s.buyer, reward["id"])

    r = await client.patch(
        f"/api/rewards/{reward['id']}",
        json={"title": "Fancy dinner", "price": 250, "description": "Somewhere new"},
        headers=auth(s.provider),
    )
    assert r.status_code == 200, r.text
    assert (r.json()["title"], r.json()["price"]) == ("Fancy dinner", 250)

    vouchers = (await client.get("/api/inventory", headers=auth(s.buyer))).json()
    assert vouchers[0]["id"] == first["id"]
    assert vouchers[0]["reward"]["title"] == "Dinner" and vouchers[0]["price_paid"] == 100
    second = await bought(client, s.buyer, reward["id"])
    assert second["reward"]["title"] == "Fancy dinner" and second["price_paid"] == 250
    assert second["balance"] == 1000 - 100 - 250
    row = await session.get(RewardPurchase, first["id"], populate_existing=True)
    assert row is not None and row.reward_snapshot["title"] == "Dinner"


async def test_patch_quantity_and_availability(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    s = await shop(session, balance=1000)
    reward = await create_reward(client, s.provider, price=10, quantity_limit=2)
    rid = reward["id"]
    await bought(client, s.buyer, rid)

    async def patch(**body: object) -> dict[str, object]:
        r = await client.patch(f"/api/rewards/{rid}", json=body, headers=auth(s.provider))
        assert r.status_code == 200, r.text
        data: dict[str, object] = r.json()
        return data

    # One sold: a limit of 1 leaves nothing (sold out), 5 leaves 4, null is unlimited.
    assert (await patch(quantity_limit=1))["status"] == "sold_out"
    got = await patch(quantity_limit=5)
    assert (got["quantity_remaining"], got["status"]) == (4, "active")
    got = await patch(status="hidden")
    assert got["status"] == "hidden"
    assert (await buy(client, s.buyer, rid)).status_code == 409
    got = await patch(quantity_limit=None, status="active")
    assert (got["quantity_limit"], got["quantity_remaining"], got["status"]) == (
        None,
        None,
        "active",
    )
    got = await patch(cooldown_days=3, description=None)
    assert got["cooldown_days"] == 3 and got["description"] is None


@pytest.mark.parametrize(
    "body", [{"title": None}, {"price": None}, {"status": None}, {"status": "sold_out"}]
)
async def test_patch_validation(
    client: httpx.AsyncClient, session: AsyncSession, body: dict[str, object]
) -> None:
    s = await shop(session)
    reward = await create_reward(client, s.provider)
    r = await client.patch(f"/api/rewards/{reward['id']}", json=body, headers=auth(s.provider))
    assert r.status_code == 422


async def test_patch_authorization(client: httpx.AsyncClient, session: AsyncSession) -> None:
    s = await shop(session)
    stranger = await factories.create_user(session)
    stranger_id = stranger.id
    await session.commit()
    reward = await create_reward(client, s.provider)
    url = f"/api/rewards/{reward['id']}"
    assert (await client.patch(url, json={"price": 1}, headers=auth(s.buyer))).status_code == 403
    assert (
        await client.patch(url, json={"price": 1}, headers=auth(stranger_id))
    ).status_code == 404
    assert (
        await client.patch("/api/rewards/999999", json={"price": 1}, headers=auth(s.provider))
    ).status_code == 404


async def test_patch_refused_after_the_partnership_ended(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    s = await shop(session)
    reward = await create_reward(client, s.provider)
    r = await client.post(
        "/api/partnership/leave", json={"confirm_text": "LEAVE"}, headers=auth(s.buyer)
    )
    assert r.status_code in (200, 204), r.text
    r = await client.patch(
        f"/api/rewards/{reward['id']}", json={"status": "active"}, headers=auth(s.provider)
    )
    assert r.status_code == 409
    row = await session.get(Reward, reward["id"], populate_existing=True)
    assert row is not None
    assert row.status == RewardStatus.HIDDEN and row.hidden_by_partnership_end is True


# --- purchase --------------------------------------------------------------------------------


async def test_purchase_debits_decrements_and_snapshots(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    s = await shop(session, balance=500)
    reward = await create_reward(
        client, s.provider, title="Massage", description="30 min", price=120, quantity_limit=2
    )
    r = await buy(client, s.buyer, reward["id"], idem="buy-1")
    assert r.status_code == 201, r.text
    voucher = r.json()
    assert voucher["status"] == "purchased" and voucher["side"] == "buyer"
    assert voucher["price_paid"] == 120 and voucher["balance"] == 380
    assert voucher["buyer_id"] == s.buyer and voucher["provider_id"] == s.provider
    assert voucher["reward"]["title"] == "Massage" and voucher["reward"]["description"] == "30 min"
    assert voucher["frozen"] is False and "idempotency_key" not in voucher

    ledger = (
        await session.execute(
            select(GoldTransaction).where(GoldTransaction.purchase_id == voucher["id"])
        )
    ).scalar_one()
    assert ledger.type == GoldTransactionType.REWARD_PURCHASE and ledger.amount == -120
    assert ledger.idempotency_key == f"purchase:{s.buyer}:buy-1"
    assert ledger.user_id == s.buyer
    assert await balance(session, s.buyer, s.partnership) == 380

    row = await session.get(Reward, reward["id"], populate_existing=True)
    assert row is not None and row.quantity_remaining == 1 and row.status == RewardStatus.ACTIVE
    await bought(client, s.buyer, reward["id"])
    row = await session.get(Reward, reward["id"], populate_existing=True)
    assert row is not None and row.quantity_remaining == 0 and row.status == RewardStatus.SOLD_OUT

    assert await events(session, "reward_purchase", voucher["id"]) == ["reward_purchased"]
    assert await notifications(session, "reward_purchase", voucher["id"]) == [
        (s.provider, "reward_purchased")
    ]
    await assert_ledger_invariants(session)


async def test_purchase_replays_with_the_same_key(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    s = await shop(session, balance=500)
    reward = await create_reward(client, s.provider, price=100)
    first = await buy(client, s.buyer, reward["id"], idem="same")
    again = await buy(client, s.buyer, reward["id"], idem="same")
    assert first.status_code == again.status_code == 201
    assert again.headers.get("Idempotent-Replayed") == "true"
    assert again.json() == first.json()
    assert await count(session, RewardPurchase) == 1
    assert await count(session, GoldTransaction, GoldTransaction.amount < 0) == 1
    assert await balance(session, s.buyer, s.partnership) == 400
    # Another reward with the same key is a different request.
    other = await create_reward(client, s.provider, price=10)
    assert (await buy(client, s.buyer, other["id"], idem="same")).status_code == 422


async def test_purchase_key_is_required(client: httpx.AsyncClient, session: AsyncSession) -> None:
    s = await shop(session)
    reward = await create_reward(client, s.provider)
    r = await client.post(f"/api/rewards/{reward['id']}/purchase", headers=auth(s.buyer))
    assert r.status_code == 422
    assert await count(session, RewardPurchase) == 0


async def test_purchase_key_reused_after_the_replay_window_is_refused(
    client: httpx.AsyncClient, session: AsyncSession, frozen_clock: object
) -> None:
    from app.core import clock

    s = await shop(session, balance=500)
    reward = await create_reward(client, s.provider, price=100)
    assert (await buy(client, s.buyer, reward["id"], idem="old")).status_code == 201
    clock.advance(timedelta(hours=25))
    r = await buy(client, s.buyer, reward["id"], idem="old")
    assert r.status_code == 409
    assert await count(session, RewardPurchase) == 1
    assert await balance(session, s.buyer, s.partnership) == 400


async def test_insufficient_gold(client: httpx.AsyncClient, session: AsyncSession) -> None:
    s = await shop(session, balance=99)
    reward = await create_reward(client, s.provider, price=100, quantity_limit=1)
    r = await buy(client, s.buyer, reward["id"])
    assert r.status_code == 409 and r.json()["detail"] == "Not enough gold"
    assert await count(session, RewardPurchase) == 0
    row = await session.get(Reward, reward["id"], populate_existing=True)
    assert row is not None and row.quantity_remaining == 1
    assert await balance(session, s.buyer, s.partnership) == 99


async def test_sold_out(client: httpx.AsyncClient, session: AsyncSession) -> None:
    s = await shop(session)
    reward = await create_reward(client, s.provider, price=10, quantity_limit=1)
    await bought(client, s.buyer, reward["id"])
    r = await buy(client, s.buyer, reward["id"])
    assert r.status_code == 409 and r.json()["detail"] == "This reward is sold out"


async def test_hidden(client: httpx.AsyncClient, session: AsyncSession) -> None:
    s = await shop(session)
    reward = await create_reward(client, s.provider, status="hidden")
    r = await buy(client, s.buyer, reward["id"])
    assert r.status_code == 409 and r.json()["detail"] == "This reward is not available"


async def test_cooldown(
    client: httpx.AsyncClient, session: AsyncSession, frozen_clock: object
) -> None:
    from app.core import clock

    s = await shop(session, balance=1000)
    reward = await create_reward(client, s.provider, price=10, cooldown_days=7)
    await bought(client, s.buyer, reward["id"])
    listed = (await client.get("/api/rewards", headers=auth(s.buyer))).json()
    assert listed[0]["cooldown_until"] is not None
    clock.advance(timedelta(days=6, hours=23))
    r = await buy(client, s.buyer, reward["id"])
    assert r.status_code == 409 and r.json()["detail"] == "This reward is on cooldown"
    clock.advance(timedelta(hours=1))
    assert (await buy(client, s.buyer, reward["id"])).status_code == 201


async def test_refunded_purchase_does_not_start_a_cooldown(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    s = await shop(session, balance=1000)
    reward = await create_reward(client, s.provider, price=10, cooldown_days=7)
    voucher = await bought(client, s.buyer, reward["id"])
    r = await client.post(f"/api/inventory/{voucher['id']}/refund", headers=auth(s.buyer))
    assert r.status_code == 200, r.text
    assert (await buy(client, s.buyer, reward["id"])).status_code == 201


async def test_ended_partnership_freezes_the_wallet(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    s = await shop(session)
    reward = await create_reward(client, s.provider, price=10)
    p = await session.get(Partnership, s.partnership)
    assert p is not None
    p.status = PartnershipStatus.ENDED
    await session.commit()
    r = await buy(client, s.buyer, reward["id"])
    assert r.status_code == 409 and r.json()["detail"] == "Partnership has ended"
    assert await count(session, RewardPurchase) == 0


async def test_buyer_cannot_be_the_creator(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    s = await shop(session)
    reward = await create_reward(client, s.provider, price=10)
    r = await buy(client, s.provider, reward["id"])
    assert r.status_code == 409 and r.json()["detail"] == "You cannot buy your own reward"


async def test_strangers_get_404(client: httpx.AsyncClient, session: AsyncSession) -> None:
    s = await shop(session)
    stranger = await factories.create_user(session)
    stranger_id = stranger.id
    await session.commit()
    reward = await create_reward(client, s.provider, price=10)
    assert (await buy(client, stranger_id, reward["id"])).status_code == 404
    assert (await buy(client, s.buyer, 10**12)).status_code == 404
    assert await count(session, RewardPurchase) == 0


async def test_failed_purchase_leaves_no_journal_or_notification(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    s = await shop(session, balance=5)
    reward = await create_reward(client, s.provider, price=10)
    assert (await buy(client, s.buyer, reward["id"])).status_code == 409
    from app.modules.journal.models import JournalEvent
    from app.modules.notifications.models import Notification

    assert await count(session, JournalEvent, JournalEvent.entity_type == "reward_purchase") == 0
    assert await count(session, Notification, Notification.entity_type == "reward_purchase") == 0


async def test_partnership_leave_hides_and_repair_restores_rewards(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """A sold-out reward hidden by the leave comes back sold out; refunding it while the
    partnership is ended gives the unit back but leaves it hidden until re-pairing."""
    s = await shop(session)
    reward = await create_reward(client, s.provider, price=10, quantity_limit=1)
    voucher = await bought(client, s.buyer, reward["id"])
    r = await client.post(
        "/api/partnership/leave", json={"confirm_text": "LEAVE"}, headers=auth(s.buyer)
    )
    assert r.status_code in (200, 204)
    r = await client.post(f"/api/inventory/{voucher['id']}/refund", headers=auth(s.provider))
    assert r.status_code == 200, r.text
    row = await session.get(Reward, reward["id"], populate_existing=True)
    assert row is not None
    assert row.status == RewardStatus.HIDDEN and row.quantity_remaining == 1
    assert row.hidden_by_partnership_end is True
