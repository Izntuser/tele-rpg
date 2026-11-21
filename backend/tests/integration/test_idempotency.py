"""``Idempotency-Key`` on /submit and /confirm: a repeat replays the stored response without
applying the effect again; a key is per user, bound to one request, validated, expires after
24h, and failed requests are not cached. Includes parallel same-key requests over separate
connections."""

import asyncio
from datetime import timedelta
from types import ModuleType

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import clock, idempotency, ratelimit
from app.modules.common.models import IdempotencyKey
from app.modules.economy.models import GoldTransaction
from app.modules.progression.models import XpTransaction
from app.modules.quests.models import QuestSubmission
from app.modules.users.models import User
from tests import factories
from tests.integration.completion_support import (
    active_quest,
    app_client,
    auth,
    count,
    ident,
    pair,
    wallet_balance,
)


@pytest.fixture(autouse=True)
def _clean_limiters() -> None:
    ratelimit.reset_all()


async def act(
    client: httpx.AsyncClient,
    user: User | int,
    occurrence_id: int,
    action: str,
    key: str | None,
    body: dict[str, object] | None = None,
) -> httpx.Response:
    headers = auth(user, **({"Idempotency-Key": key} if key is not None else {}))
    return await client.post(f"/api/quests/{occurrence_id}/{action}", headers=headers, json=body)


async def test_repeated_submit_replays_the_stored_response(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    occ = await active_quest(session, gm, player)

    first = await act(client, player, occ, "submit", "submit-1", {"comment": "done"})
    assert first.status_code == 200, first.text
    assert "Idempotent-Replayed" not in first.headers
    again = await act(client, player, occ, "submit", "submit-1", {"comment": "done"})
    assert again.status_code == 200
    assert again.headers["Idempotent-Replayed"] == "true"
    assert again.json() == first.json()
    assert await count(session, QuestSubmission) == 1


async def test_repeated_confirm_pays_once(client: httpx.AsyncClient, session: AsyncSession) -> None:
    gm, player, partnership = await pair(session)
    occ = await active_quest(session, gm, player)
    await act(client, player, occ, "submit", None)

    responses = [await act(client, gm, occ, "confirm", "confirm-1") for _ in range(3)]
    assert [r.status_code for r in responses] == [200, 200, 200]
    assert responses[0].json()["completion"]["gold"] == 40
    assert all(r.json() == responses[0].json() for r in responses)
    assert await count(session, GoldTransaction) == 1
    assert await count(session, XpTransaction) == 1
    assert await wallet_balance(session, player, partnership) == 40
    # Without the key a repeat is just a second (refused) confirm.
    assert (await act(client, gm, occ, "confirm", None)).status_code == 409


async def test_auto_confirm_submit_with_a_key_pays_once(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, partnership = await pair(session)
    occ = await active_quest(session, gm, player, confirmation="auto")
    for _ in range(3):
        response = await act(client, player, occ, "submit", "auto-1")
        assert response.status_code == 200
        assert response.json()["status"] == "completed"
    assert await count(session, GoldTransaction) == 1
    assert await wallet_balance(session, player, partnership) == 40


async def test_key_reused_for_a_different_request_is_422(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    occ = await active_quest(session, gm, player)
    other = await active_quest(session, gm, player)
    assert (await act(client, player, occ, "submit", "k", {"comment": "a"})).status_code == 200

    different_body = await act(client, player, occ, "submit", "k", {"comment": "b"})
    assert different_body.status_code == 422
    different_quest = await act(client, player, other, "submit", "k", {"comment": "a"})
    assert different_quest.status_code == 422
    assert await count(session, QuestSubmission) == 1


async def test_keys_are_scoped_per_user(client: httpx.AsyncClient, session: AsyncSession) -> None:
    gm, player, _ = await pair(session)
    occ = await active_quest(session, gm, player)
    assert (await act(client, player, occ, "submit", "same")).status_code == 200
    confirmed = await act(client, gm, occ, "confirm", "same")
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "completed"
    rows = (await session.scalars(select(IdempotencyKey).order_by(IdempotencyKey.user_id))).all()
    assert {(r.user_id, r.key) for r in rows} == {(ident(gm), "same"), (ident(player), "same")}


async def test_failed_requests_are_not_cached(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    occ = await active_quest(session, gm, player)

    too_early = await act(client, gm, occ, "confirm", "retry-me")
    assert too_early.status_code == 409
    assert await count(session, IdempotencyKey) == 0
    assert (await act(client, player, occ, "submit", None)).status_code == 200
    assert (await act(client, gm, occ, "confirm", "retry-me")).status_code == 200
    assert await count(session, GoldTransaction) == 1


@pytest.mark.parametrize("key", ["", "x" * (idempotency.MAX_KEY_LEN + 1), "has space", "tab\t"])
async def test_invalid_keys_are_422(
    client: httpx.AsyncClient, session: AsyncSession, key: str
) -> None:
    gm, player, _ = await pair(session)
    occ = await active_quest(session, gm, player)
    response = await act(client, player, occ, "submit", key)
    assert response.status_code == 422
    assert await count(session, QuestSubmission) == 0


async def test_longest_key_is_accepted(client: httpx.AsyncClient, session: AsyncSession) -> None:
    gm, player, _ = await pair(session)
    occ = await active_quest(session, gm, player)
    key = "k" * idempotency.MAX_KEY_LEN
    assert (await act(client, player, occ, "submit", key)).status_code == 200


async def test_expired_keys_run_again(
    client: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    gm, player, _ = await pair(session)
    occ = await active_quest(session, gm, player)
    await act(client, player, occ, "submit", None)
    assert (await act(client, gm, occ, "confirm", "old")).status_code == 200

    frozen_clock.advance(idempotency.TTL + timedelta(minutes=1))
    # The stored response is gone, so the repeat is a real (refused) second confirm.
    assert (await act(client, gm, occ, "confirm", "old")).status_code == 409
    assert await count(session, GoldTransaction) == 1


async def test_an_expired_stored_response_is_never_replayed(
    session: AsyncSession, frozen_clock: ModuleType
) -> None:
    """Expiry holds without the purge job: an old row is taken over, not replayed."""
    _, player, _ = await pair(session)
    session.add(
        IdempotencyKey(
            user_id=player.id,
            key="stale",
            endpoint="submit",
            response={
                "state": "done",
                "request_hash": "h",
                "status_code": 200,
                "body": {"old": True},
            },
            created_at=clock.now() - idempotency.TTL - timedelta(seconds=1),
        )
    )
    await session.flush()

    claimed = await idempotency.claim(
        session, user_id=player.id, key="stale", endpoint="submit", request_hash="h"
    )
    assert isinstance(claimed, idempotency.Claim)
    row = await session.scalar(
        select(IdempotencyKey)
        .where(IdempotencyKey.key == "stale")
        .execution_options(populate_existing=True)
    )
    assert row is not None
    assert row.created_at == clock.now() and row.response["state"] == "in_progress"


async def test_account_deletion_drops_the_companions_stored_responses(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """A stored quest response carries both members' free text; once one member deletes their
    account, the companion's cached copy is gone and cannot replay it."""
    gm, player, _ = await pair(session)
    occ = await active_quest(session, gm, player)
    stranger = await factories.create_user(session)
    session.add(
        IdempotencyKey(
            user_id=stranger.id, key="unrelated", endpoint="x", response={}, created_at=clock.now()
        )
    )
    await session.flush()
    gm_id, player_id, stranger_id = ident(gm), ident(player), ident(stranger)

    submitted = await act(client, player, occ, "submit", "s1", {"comment": "my secret note"})
    assert submitted.status_code == 200
    confirmed = await act(client, gm, occ, "confirm", "c1")
    assert confirmed.status_code == 200 and "my secret note" in confirmed.text

    deleted = await client.request(
        "DELETE", "/api/account", headers=auth(player_id), json={"confirm_text": "DELETE"}
    )
    assert deleted.status_code == 204
    owners = (await session.scalars(select(IdempotencyKey.user_id))).all()
    assert owners == [stranger_id]

    again = await act(client, gm_id, occ, "confirm", "c1")
    assert "Idempotent-Replayed" not in again.headers
    assert again.status_code == 409 and "my secret note" not in again.text


async def test_purge_expired(session: AsyncSession, frozen_clock: ModuleType) -> None:
    gm, player, _ = await pair(session)
    for key, age in (("fresh", timedelta(hours=1)), ("stale", timedelta(hours=25))):
        session.add(
            IdempotencyKey(
                user_id=player.id,
                key=key,
                endpoint="test",
                response={"state": "done"},
                created_at=clock.now() - age,
            )
        )
    await session.flush()
    assert await idempotency.purge_expired(session) == 1
    keys = (await session.scalars(select(IdempotencyKey.key))).all()
    assert keys == ["fresh"]


def test_fingerprint_ignores_key_order() -> None:
    assert idempotency.fingerprint({"a": 1, "b": None}) == idempotency.fingerprint(
        {"b": None, "a": 1}
    )
    assert idempotency.fingerprint({"a": 1}) != idempotency.fingerprint({"a": 2})


async def test_parallel_requests_with_one_key_apply_once(
    independent_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with independent_sessions() as s:
        gm, player, partnership = await pair(s)
        occ = await active_quest(s, gm, player)
        gm_id, player_id, partnership_id = gm.id, player.id, partnership.id
        await s.commit()

    async with app_client(independent_sessions) as client:
        assert (await act(client, player_id, occ, "submit", None)).status_code == 200
        responses = await asyncio.gather(
            *(act(client, gm_id, occ, "confirm", "parallel") for _ in range(8))
        )
    assert [r.status_code for r in responses] == [200] * 8
    assert all(r.json() == responses[0].json() for r in responses)
    assert sum("Idempotent-Replayed" not in r.headers for r in responses) == 1

    async with independent_sessions() as s:
        assert await count(s, GoldTransaction) == 1
        assert await count(s, XpTransaction) == 1
        balance = await s.scalar(
            select(GoldTransaction.amount).where(GoldTransaction.partnership_id == partnership_id)
        )
        assert balance == 40
