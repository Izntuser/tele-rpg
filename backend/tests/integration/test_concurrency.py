"""Races over separate connections (real commits, real row locks): parallel confirms pay
exactly once, parallel completions for one wallet lose no update, and confirm racing redo /
leave / a second auto-submit always ends in one consistent outcome. The forced-interleaving
tests pin the lock order of DECISIONS #16: a payout already holding the partnership
``FOR SHARE`` never deadlocks (40P01) with ``leave`` or account deletion."""

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import idempotency, ratelimit
from app.modules.common.enums import QuestOccurrenceStatus
from app.modules.economy.models import GoldTransaction, Wallet
from app.modules.partnerships import service as partnerships
from app.modules.partnerships.models import Partnership
from app.modules.progression.models import XpTransaction
from app.modules.quests import completion, service
from app.modules.quests.models import QuestOccurrence
from app.modules.quests.schemas import ConfirmIn, RedoIn, SubmitIn
from app.modules.users import account
from app.modules.users.models import Character, User
from tests.integration.completion_support import (
    active_quest,
    app_client,
    assert_ledger_invariants,
    auth,
    count,
    pair,
)

Sessions = async_sessionmaker[AsyncSession]


@pytest.fixture(autouse=True)
def _clean_limiters() -> None:
    ratelimit.reset_all()


async def seed(
    sessions: Sessions, quests: int = 1, **terms: Any
) -> tuple[int, int, int, list[int]]:
    """(gm id, player id, partnership id, occurrence ids), committed."""
    async with sessions() as s:
        gm, player, partnership = await pair(s)
        ids = [await active_quest(s, gm, player, **terms) for _ in range(quests)]
        out = (gm.id, player.id, partnership.id, ids)
        await s.commit()
    return out


async def as_user(
    sessions: Sessions, user_id: int, fn: Callable[[AsyncSession, User], Awaitable[Any]]
) -> Any:
    async with sessions() as s:
        user = await s.get(User, user_id)
        assert user is not None
        return await fn(s, user)


async def submit(sessions: Sessions, player_id: int, occ: int) -> Any:
    return await as_user(sessions, player_id, lambda s, u: completion.submit(s, u, occ, SubmitIn()))


async def confirm(sessions: Sessions, gm_id: int, occ: int) -> Any:
    return await as_user(sessions, gm_id, lambda s, u: completion.confirm(s, u, occ, ConfirmIn()))


async def test_ten_parallel_confirms_pay_exactly_once(independent_sessions: Sessions) -> None:
    gm_id, player_id, _, [occ] = await seed(independent_sessions)
    await submit(independent_sessions, player_id, occ)

    results = await asyncio.gather(
        *(confirm(independent_sessions, gm_id, occ) for _ in range(10)), return_exceptions=True
    )
    winners = [r for r in results if not isinstance(r, BaseException)]
    assert len(winners) == 1
    assert all(isinstance(r, service.QuestStateError) for r in results if r not in winners)
    async with independent_sessions() as s:
        assert await count(s, GoldTransaction) == 1
        assert await count(s, XpTransaction) == 1
        character = await s.scalar(select(Character).where(Character.user_id == player_id))
        assert character is not None and character.total_xp == 50
        await assert_ledger_invariants(s)


async def test_ten_parallel_confirms_over_http_pay_exactly_once(
    independent_sessions: Sessions,
) -> None:
    gm_id, player_id, _, [occ] = await seed(independent_sessions)
    async with app_client(independent_sessions) as client:
        submitted = await client.post(f"/api/quests/{occ}/submit", headers=auth(player_id))
        assert submitted.status_code == 200
        responses = await asyncio.gather(
            *(client.post(f"/api/quests/{occ}/confirm", headers=auth(gm_id)) for _ in range(10))
        )
    assert sorted(r.status_code for r in responses) == [200] + [409] * 9
    async with independent_sessions() as s:
        assert await count(s, GoldTransaction) == 1
        assert await count(s, XpTransaction) == 1
        await assert_ledger_invariants(s)


async def test_parallel_auto_submits_pay_exactly_once(independent_sessions: Sessions) -> None:
    _, player_id, _, [occ] = await seed(independent_sessions, confirmation="auto")
    results = await asyncio.gather(
        *(submit(independent_sessions, player_id, occ) for _ in range(10)), return_exceptions=True
    )
    assert sum(not isinstance(r, BaseException) for r in results) == 1
    async with independent_sessions() as s:
        assert await count(s, GoldTransaction) == 1
        assert await count(s, XpTransaction) == 1


async def test_parallel_completions_into_one_wallet_lose_no_update(
    independent_sessions: Sessions,
) -> None:
    gm_id, player_id, partnership_id, occs = await seed(independent_sessions, quests=8)
    for occ in occs:
        await submit(independent_sessions, player_id, occ)

    results = await asyncio.gather(
        *(confirm(independent_sessions, gm_id, occ) for occ in occs), return_exceptions=True
    )
    assert not [r for r in results if isinstance(r, BaseException)]
    async with independent_sessions() as s:
        balance = await s.scalar(
            select(Wallet.balance).where(
                Wallet.user_id == player_id, Wallet.partnership_id == partnership_id
            )
        )
        assert balance == 8 * 40
        await assert_ledger_invariants(s)
        character = await s.scalar(select(Character).where(Character.user_id == player_id))
        assert character is not None and character.total_xp == 8 * 50
        assert await count(s, GoldTransaction) == 8


async def test_confirm_racing_redo_has_one_winner(independent_sessions: Sessions) -> None:
    gm_id, player_id, _, [occ] = await seed(independent_sessions)
    await submit(independent_sessions, player_id, occ)

    redo = as_user(
        independent_sessions,
        gm_id,
        lambda s, u: completion.request_redo(s, u, occ, RedoIn(reason="again")),
    )
    results = await asyncio.gather(
        confirm(independent_sessions, gm_id, occ), redo, return_exceptions=True
    )
    async with independent_sessions() as s:
        occurrence = await s.get(QuestOccurrence, occ)
        assert occurrence is not None
        paid = await count(s, GoldTransaction)
    if not isinstance(results[0], BaseException):
        assert isinstance(results[1], service.QuestStateError)
        assert occurrence.status == QuestOccurrenceStatus.COMPLETED and paid == 1
    else:
        assert isinstance(results[0], service.QuestStateError)
        assert not isinstance(results[1], BaseException)
        assert occurrence.status == QuestOccurrenceStatus.ACTIVE and paid == 0


async def test_confirm_racing_leave_never_pays_on_an_ended_partnership(
    independent_sessions: Sessions,
) -> None:
    gm_id, player_id, _, [occ] = await seed(independent_sessions)
    await submit(independent_sessions, player_id, occ)

    leave = as_user(independent_sessions, player_id, lambda s, u: partnerships.leave(s, u, "LEAVE"))
    results = await asyncio.gather(
        confirm(independent_sessions, gm_id, occ), leave, return_exceptions=True
    )
    assert not isinstance(results[1], BaseException)
    async with independent_sessions() as s:
        occurrence = await s.get(QuestOccurrence, occ)
        assert occurrence is not None
        paid = await count(s, GoldTransaction)
        await assert_ledger_invariants(s)
    if isinstance(results[0], BaseException):
        # leave won: the in-review quest was cancelled and nothing was paid.
        assert isinstance(results[0], service.PartnershipInactiveError)
        assert occurrence.status == QuestOccurrenceStatus.CANCELLED and paid == 0
    else:
        # confirm won: it was completed and paid before the partnership ended.
        assert occurrence.status == QuestOccurrenceStatus.COMPLETED and paid == 1


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


async def hold_partnership_then_confirm(
    sessions: Sessions,
    gm_id: int,
    partnership_id: int,
    occ: int,
    ender: Callable[[], Coroutine[Any, Any, Any]],
) -> tuple[Any, Any]:
    """Forced interleaving: (1) the confirm's transaction takes the partnership FOR SHARE (its
    first lock), (2) ``ender`` (leave / account deletion) starts, locks the user rows and
    blocks on the partnership, (3) only then the confirm writes its FK rows (ledger, XP,
    journal, notification), each FK check taking FOR KEY SHARE on a user row. With a full
    FOR UPDATE on the user rows this was a lock cycle that Postgres broke with 40P01."""
    async with sessions() as s:
        await s.execute(
            select(Partnership.id)
            .where(Partnership.id == partnership_id)
            .with_for_update(read=True)
        )
        ending: asyncio.Task[Any] = asyncio.create_task(ender())
        await wait_for_lock_waiter(sessions)
        assert not ending.done()
        gm = await s.get(User, gm_id)
        assert gm is not None
        confirmed = await asyncio.wait_for(completion.confirm(s, gm, occ, ConfirmIn()), 10)
    ended = await asyncio.wait_for(ending, 10)
    return confirmed, ended


async def test_leave_waiting_on_a_payout_does_not_deadlock(independent_sessions: Sessions) -> None:
    gm_id, player_id, partnership_id, [occ] = await seed(independent_sessions)
    await submit(independent_sessions, player_id, occ)

    confirmed, _ = await hold_partnership_then_confirm(
        independent_sessions,
        gm_id,
        partnership_id,
        occ,
        lambda: as_user(
            independent_sessions, player_id, lambda s, u: partnerships.leave(s, u, "LEAVE")
        ),
    )
    assert confirmed.completion is not None
    async with independent_sessions() as s:
        occurrence = await s.get(QuestOccurrence, occ)
        partnership = await s.get(Partnership, partnership_id)
        assert occurrence is not None and occurrence.status == QuestOccurrenceStatus.COMPLETED
        assert partnership is not None and partnership.status.value == "ended"
        assert await count(s, GoldTransaction) == 1
        await assert_ledger_invariants(s)


async def test_account_deletion_waiting_on_a_payout_does_not_deadlock(
    independent_sessions: Sessions,
) -> None:
    gm_id, player_id, partnership_id, [occ] = await seed(independent_sessions)
    await submit(independent_sessions, player_id, occ)

    confirmed, _ = await hold_partnership_then_confirm(
        independent_sessions,
        gm_id,
        partnership_id,
        occ,
        lambda: as_user(
            independent_sessions,
            player_id,
            lambda s, u: account.delete_account(s, u, "DELETE"),
        ),
    )
    assert confirmed.completion is not None
    async with independent_sessions() as s:
        occurrence = await s.get(QuestOccurrence, occ)
        player = await s.get(User, player_id)
        assert occurrence is not None and occurrence.status == QuestOccurrenceStatus.COMPLETED
        assert player is not None and player.deleted_at is not None
        assert player.tg_user_id == -player_id
        assert await count(s, GoldTransaction) == 1
        await assert_ledger_invariants(s)


async def test_account_deletion_is_not_blocked_by_my_own_pending_idempotent_submit(
    independent_sessions: Sessions,
) -> None:
    """The player's own submit claims its Idempotency-Key (an FK check: FOR KEY SHARE on the
    player's row) and has not reached the partnership yet. Deletion rewrites tg_user_id; with a
    full unique constraint that was a key update (implicit FOR UPDATE) that would wait for the
    submit while the submit waits for deletion's partnership lock. With the partial unique
    index (migration 0005) the rewrite is a no-key update: deletion finishes, the submit then
    sees the ended partnership and is refused."""
    _, player_id, _, [occ] = await seed(independent_sessions)

    async with independent_sessions() as s:
        claim = await idempotency.claim(
            s, user_id=player_id, key="mine", endpoint="submit", request_hash="h"
        )
        assert isinstance(claim, idempotency.Claim)

        async def delete_me() -> None:
            async with independent_sessions() as d:
                await d.execute(text("SET LOCAL lock_timeout = '5s'"))
                user = await d.get(User, player_id)
                assert user is not None
                await account.delete_account(d, user, "DELETE")

        await asyncio.wait_for(delete_me(), 10)
        player = await s.get(User, player_id)
        assert player is not None
        with pytest.raises(service.PartnershipInactiveError):
            await completion.submit(s, player, occ, SubmitIn(), idempotency=claim)
        await s.rollback()

    async with independent_sessions() as s:
        assert await count(s, GoldTransaction) == 0
        occurrence = await s.get(QuestOccurrence, occ)
        assert occurrence is not None and occurrence.status == QuestOccurrenceStatus.CANCELLED
