"""Shop races over separate connections (real commits, real row locks).

- parallel purchases of the last unit sell it exactly once (service and HTTP);
- parallel purchases with one Idempotency-Key charge once and replay;
- parallel purchases never overdraw a wallet; parallel refunds credit once;
- a concurrent mix of purchases and refunds keeps ``wallet.balance == sum(ledger)`` and
  ``quantity_remaining == quantity_limit - live purchases``;
- forced interleavings pin the lock order (DECISIONS #16, #17): a purchase or refund already
  holding the partnership ``FOR SHARE`` never deadlocks (40P01) with ``leave`` or account
  deletion, which lock the user rows first and then wait for the partnership; and a purchase
  that loses the race to ``leave`` is refused (frozen wallet) without any effect.
"""

import asyncio
import random
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import ratelimit
from app.modules.common.enums import (
    GoldTransactionType,
    PartnershipStatus,
    RewardPurchaseStatus,
    RewardStatus,
)
from app.modules.economy.models import GoldTransaction, Wallet
from app.modules.inventory import service as inventory
from app.modules.partnerships import service as partnerships
from app.modules.partnerships.models import Partnership
from app.modules.rewards import service as rewards
from app.modules.rewards.models import Reward, RewardPurchase
from app.modules.users import account
from app.modules.users.models import User
from tests import factories
from tests.integration.completion_support import (
    app_client,
    assert_ledger_invariants,
    auth,
    count,
)

Sessions = async_sessionmaker[AsyncSession]


@pytest.fixture(autouse=True)
def _clean_limiters() -> None:
    ratelimit.reset_all()


async def seed(
    sessions: Sessions, *, balance: int = 1000, price: int = 10, quantity: int | None = 1
) -> tuple[int, int, int, int]:
    """(provider id, buyer id, partnership id, reward id), committed."""
    async with sessions() as s:
        provider = await factories.create_user(s)
        buyer = await factories.create_user(s)
        partnership = await factories.create_partnership(s, provider, buyer)
        await factories.create_wallet(s, provider, partnership)
        await factories.create_wallet(s, buyer, partnership, balance=balance)
        reward = await factories.create_reward(
            s, partnership, provider, price=price, quantity_limit=quantity
        )
        out = (provider.id, buyer.id, partnership.id, reward.id)
        await s.commit()
    return out


async def as_user(
    sessions: Sessions, user_id: int, fn: Callable[[AsyncSession, User], Awaitable[Any]]
) -> Any:
    async with sessions() as s:
        user = await s.get(User, user_id)
        assert user is not None
        return await fn(s, user)


async def purchase(sessions: Sessions, buyer_id: int, reward_id: int, key: str) -> Any:
    return await as_user(
        sessions, buyer_id, lambda s, u: rewards.purchase(s, u, reward_id, client_key=key)
    )


async def refund(sessions: Sessions, user_id: int, purchase_id: int) -> Any:
    return await as_user(sessions, user_id, lambda s, u: inventory.refund(s, u, purchase_id))


async def assert_quantity_consistent(s: AsyncSession, reward_id: int) -> None:
    reward = await s.get(Reward, reward_id, populate_existing=True)
    assert reward is not None
    live = await count(
        s,
        RewardPurchase,
        RewardPurchase.reward_id == reward_id,
        RewardPurchase.status.not_in(rewards.VOID_STATUSES),
    )
    if reward.quantity_limit is not None:
        assert reward.quantity_remaining == reward.quantity_limit - live
        if reward.quantity_remaining == 0 and reward.status != RewardStatus.HIDDEN:
            assert reward.status == RewardStatus.SOLD_OUT


async def test_parallel_purchases_of_the_last_unit_sell_once(
    independent_sessions: Sessions,
) -> None:
    _, buyer_id, partnership_id, reward_id = await seed(independent_sessions)
    results = await asyncio.gather(
        *(purchase(independent_sessions, buyer_id, reward_id, f"k{i}") for i in range(10)),
        return_exceptions=True,
    )
    wins = [r for r in results if not isinstance(r, BaseException)]
    losses = [r for r in results if isinstance(r, BaseException)]
    assert len(wins) == 1
    assert all(isinstance(e, rewards.SoldOutError) for e in losses), losses
    async with independent_sessions() as s:
        assert await count(s, RewardPurchase) == 1
        assert await count(s, GoldTransaction, GoldTransaction.amount < 0) == 1
        reward = await s.get(Reward, reward_id)
        assert reward is not None
        assert reward.quantity_remaining == 0 and reward.status == RewardStatus.SOLD_OUT
        wallet = await s.scalar(
            select(Wallet.balance).where(
                Wallet.user_id == buyer_id, Wallet.partnership_id == partnership_id
            )
        )
        assert wallet == 990
        await assert_ledger_invariants(s)


async def test_parallel_purchases_of_the_last_unit_over_http_sell_once(
    independent_sessions: Sessions,
) -> None:
    _, buyer_id, _, reward_id = await seed(independent_sessions)
    async with app_client(independent_sessions) as client:
        responses = await asyncio.gather(
            *(
                client.post(
                    f"/api/rewards/{reward_id}/purchase",
                    headers=auth(buyer_id, **{"Idempotency-Key": f"http-{i}"}),
                )
                for i in range(8)
            )
        )
    codes = sorted(r.status_code for r in responses)
    assert codes == [201] + [409] * 7, codes
    async with independent_sessions() as s:
        assert await count(s, RewardPurchase) == 1
        await assert_ledger_invariants(s)
        await assert_quantity_consistent(s, reward_id)


async def test_parallel_purchases_with_one_key_charge_once(
    independent_sessions: Sessions,
) -> None:
    _, buyer_id, _, reward_id = await seed(independent_sessions, quantity=None)
    async with app_client(independent_sessions) as client:
        responses = await asyncio.gather(
            *(
                client.post(
                    f"/api/rewards/{reward_id}/purchase",
                    headers=auth(buyer_id, **{"Idempotency-Key": "one-key"}),
                )
                for _ in range(6)
            )
        )
    assert {r.status_code for r in responses} == {201}
    assert len({r.json()["id"] for r in responses}) == 1
    assert sum(r.headers.get("Idempotent-Replayed") == "true" for r in responses) == 5
    async with independent_sessions() as s:
        assert await count(s, RewardPurchase) == 1
        assert await count(s, GoldTransaction, GoldTransaction.amount < 0) == 1
        await assert_ledger_invariants(s)


async def test_parallel_purchases_never_overdraw(independent_sessions: Sessions) -> None:
    _, buyer_id, _, reward_id = await seed(
        independent_sessions, balance=35, price=10, quantity=None
    )
    results = await asyncio.gather(
        *(purchase(independent_sessions, buyer_id, reward_id, f"o{i}") for i in range(8)),
        return_exceptions=True,
    )
    wins = [r for r in results if not isinstance(r, BaseException)]
    assert len(wins) == 3
    assert all(
        isinstance(r, rewards.InsufficientGoldError)
        for r in results
        if isinstance(r, BaseException)
    )
    async with independent_sessions() as s:
        await assert_ledger_invariants(s)
        assert await s.scalar(select(Wallet.balance).where(Wallet.user_id == buyer_id)) == 5


async def test_parallel_refunds_credit_once(independent_sessions: Sessions) -> None:
    provider_id, buyer_id, _, reward_id = await seed(independent_sessions, quantity=1)
    voucher = await purchase(independent_sessions, buyer_id, reward_id, "r")
    results = await asyncio.gather(
        *(
            refund(independent_sessions, provider_id if i % 2 else buyer_id, voucher.id)
            for i in range(6)
        ),
        return_exceptions=True,
    )
    assert sum(not isinstance(r, BaseException) for r in results) == 1
    assert all(
        isinstance(r, rewards.VoucherStateError) for r in results if isinstance(r, BaseException)
    )
    async with independent_sessions() as s:
        credits = await count(
            s, GoldTransaction, GoldTransaction.type == GoldTransactionType.REWARD_REFUND
        )
        assert credits == 1
        await assert_ledger_invariants(s)
        await assert_quantity_consistent(s, reward_id)
        reward = await s.get(Reward, reward_id)
        assert reward is not None and reward.quantity_remaining == 1


async def test_concurrent_mix_of_purchases_and_refunds_keeps_the_invariants(
    independent_sessions: Sessions,
) -> None:
    provider_id, buyer_id, _, reward_id = await seed(
        independent_sessions, balance=200, price=15, quantity=4
    )
    rng = random.Random(10)
    for wave in range(6):
        async with independent_sessions() as s:
            open_ids = list(
                await s.scalars(
                    select(RewardPurchase.id).where(
                        RewardPurchase.status == RewardPurchaseStatus.PURCHASED
                    )
                )
            )
        ops: list[Coroutine[Any, Any, Any]] = [
            purchase(independent_sessions, buyer_id, reward_id, f"mix-{wave}-{i}")
            for i in range(rng.randint(2, 5))
        ]
        for pid in rng.sample(open_ids, k=min(len(open_ids), rng.randint(0, 3))):
            ops.append(refund(independent_sessions, rng.choice([provider_id, buyer_id]), pid))
        results = await asyncio.gather(*ops, return_exceptions=True)
        for r in results:
            if isinstance(r, BaseException):
                assert isinstance(r, rewards.RewardConflictError), repr(r)
        async with independent_sessions() as s:
            await assert_ledger_invariants(s)
            await assert_quantity_consistent(s, reward_id)
            refunds = await count(
                s, GoldTransaction, GoldTransaction.type == GoldTransactionType.REWARD_REFUND
            )
            refunded = await count(
                s, RewardPurchase, RewardPurchase.status == RewardPurchaseStatus.REFUNDED
            )
            assert refunds == refunded
            debits = await count(
                s, GoldTransaction, GoldTransaction.type == GoldTransactionType.REWARD_PURCHASE
            )
            assert debits == await count(s, RewardPurchase)
    async with independent_sessions() as s:
        assert await count(s, RewardPurchase) > 4


# --- forced interleavings with leave / account deletion --------------------------------------


async def wait_for_lock_waiter(sessions: Sessions) -> None:
    """Block (up to 5s) until some other connection is waiting on a lock."""
    async with sessions() as monitor, asyncio.timeout(5):
        while True:
            waiting = await monitor.scalar(
                select(func.count())
                .select_from(text("pg_stat_activity"))
                .where(
                    text("datname = current_database()"),
                    text("wait_event_type = 'Lock'"),
                    text("pid <> pg_backend_pid()"),
                )
            )
            await monitor.rollback()
            if waiting:
                return
            await asyncio.sleep(0.02)


async def hold_partnership_then(
    sessions: Sessions,
    partnership_id: int,
    actor_id: int,
    command: Callable[[AsyncSession, User], Awaitable[Any]],
    ender: Callable[[], Coroutine[Any, Any, Any]],
) -> tuple[Any, Any]:
    """(1) the command's transaction takes the partnership FOR SHARE (its first lock), (2)
    ``ender`` starts, locks the user rows FOR NO KEY UPDATE and blocks on the partnership,
    (3) only then the command locks the reward / purchase / wallet and writes its FK rows
    (purchase, ledger, journal, notification), each FK check taking FOR KEY SHARE on a user
    row. Any lock the command needs that the ender already holds would be a 40P01 cycle."""
    async with sessions() as s:
        await s.execute(text("SET LOCAL lock_timeout = '8s'"))
        await s.execute(
            select(Partnership.id)
            .where(Partnership.id == partnership_id)
            .with_for_update(read=True)
        )
        ending: asyncio.Task[Any] = asyncio.create_task(ender())
        await wait_for_lock_waiter(sessions)
        assert not ending.done()
        actor = await s.get(User, actor_id)
        assert actor is not None
        done = await asyncio.wait_for(command(s, actor), 10)
    ended = await asyncio.wait_for(ending, 10)
    return done, ended


def leave_by(sessions: Sessions, user_id: int) -> Callable[[], Coroutine[Any, Any, Any]]:
    return lambda: as_user(sessions, user_id, lambda s, u: partnerships.leave(s, u, "LEAVE"))


def delete_account_of(sessions: Sessions, user_id: int) -> Callable[[], Coroutine[Any, Any, Any]]:
    return lambda: as_user(sessions, user_id, lambda s, u: account.delete_account(s, u, "DELETE"))


@pytest.mark.parametrize("ender", ["buyer_leaves", "provider_leaves"])
async def test_leave_waiting_on_a_purchase_does_not_deadlock(
    independent_sessions: Sessions, ender: str
) -> None:
    provider_id, buyer_id, partnership_id, reward_id = await seed(independent_sessions)
    who = buyer_id if ender == "buyer_leaves" else provider_id
    voucher, _ = await hold_partnership_then(
        independent_sessions,
        partnership_id,
        buyer_id,
        lambda s, u: rewards.purchase(s, u, reward_id, client_key="held"),
        leave_by(independent_sessions, who),
    )
    assert voucher.status == RewardPurchaseStatus.PURCHASED
    async with independent_sessions() as s:
        partnership = await s.get(Partnership, partnership_id)
        assert partnership is not None and partnership.status == PartnershipStatus.ENDED
        reward = await s.get(Reward, reward_id)
        assert reward is not None and reward.status == RewardStatus.HIDDEN
        assert reward.hidden_by_partnership_end is True
        assert await count(s, RewardPurchase) == 1
        await assert_ledger_invariants(s)


@pytest.mark.parametrize("ender", ["buyer_deletes", "provider_deletes"])
async def test_account_deletion_waiting_on_a_purchase_does_not_deadlock(
    independent_sessions: Sessions, ender: str
) -> None:
    provider_id, buyer_id, partnership_id, reward_id = await seed(independent_sessions)
    who = buyer_id if ender == "buyer_deletes" else provider_id
    voucher, _ = await hold_partnership_then(
        independent_sessions,
        partnership_id,
        buyer_id,
        lambda s, u: rewards.purchase(s, u, reward_id, client_key="held"),
        delete_account_of(independent_sessions, who),
    )
    assert voucher.price_paid == 10
    async with independent_sessions() as s:
        deleted = await s.get(User, who)
        assert deleted is not None and deleted.deleted_at is not None
        partnership = await s.get(Partnership, partnership_id)
        assert partnership is not None and partnership.status == PartnershipStatus.ENDED
        assert await count(s, RewardPurchase) == 1
        await assert_ledger_invariants(s)


async def test_account_deletion_waiting_on_a_refund_does_not_deadlock(
    independent_sessions: Sessions,
) -> None:
    provider_id, buyer_id, partnership_id, reward_id = await seed(independent_sessions)
    voucher = await purchase(independent_sessions, buyer_id, reward_id, "before")
    refunded, _ = await hold_partnership_then(
        independent_sessions,
        partnership_id,
        provider_id,
        lambda s, u: inventory.refund(s, u, voucher.id),
        delete_account_of(independent_sessions, buyer_id),
    )
    assert refunded.status == RewardPurchaseStatus.REFUNDED
    async with independent_sessions() as s:
        await assert_ledger_invariants(s)
        await assert_quantity_consistent(s, reward_id)
        assert (await s.scalar(select(Wallet.balance).where(Wallet.user_id == buyer_id))) == 1000


async def test_purchase_after_leave_won_is_refused_without_effect(
    independent_sessions: Sessions,
) -> None:
    """Reverse interleaving: leave holds the partnership FOR UPDATE; the purchase waits for
    it, then re-reads the committed (ended) status and is refused."""
    provider_id, buyer_id, partnership_id, reward_id = await seed(independent_sessions)
    async with independent_sessions() as s:
        leaver = await s.get(User, provider_id)
        assert leaver is not None
        found, _ = await partnerships.lock_active_partnership(s, leaver)
        assert found is not None
        buying = asyncio.create_task(purchase(independent_sessions, buyer_id, reward_id, "late"))
        await wait_for_lock_waiter(independent_sessions)
        await partnerships.end_partnership(s, found, leaver, payload={"reason": "left"})
        await s.commit()
    with pytest.raises(rewards.PartnershipInactiveError):
        await asyncio.wait_for(buying, 10)
    async with independent_sessions() as s:
        assert await count(s, RewardPurchase) == 0
        assert await count(s, GoldTransaction, GoldTransaction.amount < 0) == 0
        await assert_ledger_invariants(s)


async def test_purchase_racing_leave_has_one_consistent_outcome(
    independent_sessions: Sessions,
) -> None:
    _, buyer_id, partnership_id, reward_id = await seed(independent_sessions)
    results = await asyncio.gather(
        purchase(independent_sessions, buyer_id, reward_id, "race"),
        as_user(independent_sessions, buyer_id, lambda s, u: partnerships.leave(s, u, "LEAVE")),
        return_exceptions=True,
    )
    assert not isinstance(results[1], BaseException)
    async with independent_sessions() as s:
        sold = await count(s, RewardPurchase)
        await assert_ledger_invariants(s)
    if isinstance(results[0], BaseException):
        assert isinstance(results[0], rewards.PartnershipInactiveError)
        assert sold == 0
    else:
        assert sold == 1
