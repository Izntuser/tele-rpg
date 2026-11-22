"""S15 achievements: code-defined list, evaluated from ``journal.record_event`` on commit, each
unlocked once per user (PK + ON CONFLICT), with an ``achievement_unlocked`` journal event, and
read through GET /achievements."""

import asyncio
import re
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import clock, ratelimit
from app.modules.achievements import service as achievements
from app.modules.achievements.definitions import ACHIEVEMENTS, BY_CODE, TRIGGER_TYPES
from app.modules.achievements.models import AchievementUnlock
from app.modules.common.enums import JournalVisibility
from app.modules.journal.models import JournalEvent
from app.modules.journal.service import PENDING_ACHIEVEMENTS, record_event
from app.modules.users.models import User
from tests import factories
from tests.integration.completion_support import active_quest, auth, count, pair


@pytest.fixture(autouse=True)
def _clean_limiters() -> None:
    ratelimit.reset_all()


async def complete(
    client: httpx.AsyncClient, session: AsyncSession, gm: User, player: User, **terms: Any
) -> int:
    occ = await active_quest(session, gm, player, **terms)
    r = await client.post(f"/api/quests/{occ}/submit", headers=auth(player))
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/quests/{occ}/confirm", headers=auth(gm))
    assert r.status_code == 200, r.text
    return occ


async def codes(session: AsyncSession, user_id: int) -> set[str]:
    return set(
        await session.scalars(
            select(AchievementUnlock.code).where(AchievementUnlock.user_id == user_id)
        )
    )


async def unlock_events(session: AsyncSession, user_id: int) -> list[str]:
    rows = await session.scalars(
        select(JournalEvent)
        .where(JournalEvent.user_id == user_id, JournalEvent.type == achievements.UNLOCK_EVENT)
        .order_by(JournalEvent.id)
    )
    return [e.payload["code"] for e in rows]


def note(session: AsyncSession, user_id: int, type_: str, partnership_id: int | None) -> None:
    record_event(
        session,
        user_id=user_id,
        type=type_,
        partnership_id=partnership_id,
        entity_type=None,
        entity_id=None,
        payload={},
    )


# --- definitions -----------------------------------------------------------------------------


def test_about_fourteen_stable_definitions() -> None:
    assert 12 <= len(ACHIEVEMENTS) <= 16
    assert len(BY_CODE) == len(ACHIEVEMENTS)
    for a in ACHIEVEMENTS:
        assert re.fullmatch(r"[a-z0-9_]{1,64}", a.code), a.code
        assert a.target >= 1
        assert a.triggers, a.code
        assert a.icon
    assert achievements.UNLOCK_EVENT not in TRIGGER_TYPES


# --- unlocking -------------------------------------------------------------------------------


async def test_first_completion_unlocks_once_with_a_journal_event(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, partnership = await pair(session)
    await complete(client, session, gm, player)

    assert "first_quest" in await codes(session, player.id)
    assert "quest_giver" in await codes(session, gm.id)
    assert "first_quest" not in await codes(session, gm.id)
    assert await unlock_events(session, player.id) == ["first_quest"]
    event = await session.scalar(
        select(JournalEvent).where(
            JournalEvent.user_id == player.id, JournalEvent.type == achievements.UNLOCK_EVENT
        )
    )
    assert event is not None
    assert event.partnership_id == partnership.id
    assert event.payload == {"code": "first_quest"} and event.entity_type == "achievement"

    await complete(client, session, gm, player)
    assert await unlock_events(session, player.id) == ["first_quest"]
    assert await unlock_events(session, gm.id) == ["quest_giver"]
    assert (
        await count(
            session,
            AchievementUnlock,
            AchievementUnlock.user_id == player.id,
            AchievementUnlock.code == "first_quest",
        )
        == 1
    )


async def test_level_and_attribute_unlocks(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    # 2 epic quests = 500 XP: level 3; level 5 needs 700. A third epic gets 750.
    for _ in range(3):
        await complete(client, session, gm, player, difficulty="epic", attribute="physical")
    unlocked = await codes(session, player.id)
    assert {"level_5", "attribute_5"} <= unlocked
    assert "level_10" not in unlocked


async def test_companion_events_move_my_metrics(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """``mentor`` counts quests I created that my companion completed: their completion
    unlocks it for me."""
    gm, player, _ = await pair(session)
    for _ in range(10):
        await complete(client, session, gm, player, difficulty="easy", gold=10)
    assert "mentor" in await codes(session, gm.id)
    assert {"first_quest", "quests_10", "gold_100"} <= await codes(session, player.id)
    assert "mentor" not in await codes(session, player.id)


async def test_shop_unlocks(client: httpx.AsyncClient, session: AsyncSession) -> None:
    gm, player, _ = await pair(session)
    await complete(client, session, gm, player, gold=150)
    r = await client.post("/api/rewards", json={"title": "Massage", "price": 100}, headers=auth(gm))
    assert r.status_code == 201, r.text
    assert "shopkeeper" in await codes(session, gm.id)
    r = await client.post(
        f"/api/rewards/{r.json()['id']}/purchase",
        headers=auth(player, **{"Idempotency-Key": "ach-1"}),
    )
    assert r.status_code == 201, r.text
    assert "first_purchase" in await codes(session, player.id)
    assert "first_purchase" not in await codes(session, gm.id)


async def test_rolled_back_events_unlock_nothing(session: AsyncSession) -> None:
    gm, player, partnership = await pair(session)
    await session.commit()
    nested = await session.begin_nested()
    note(session, gm.id, "quest_offered", partnership.id)
    await session.flush()
    await nested.rollback()
    # The rollback dropped the note: committing now evaluates nothing.
    assert PENDING_ACHIEVEMENTS not in session.sync_session.info
    await session.commit()
    assert await codes(session, gm.id) == set()


async def test_untriggered_types_are_not_evaluated(session: AsyncSession) -> None:
    gm, _, partnership = await pair(session)
    # A quest_offered row exists, but the commit only noted an unrelated type.
    session.add(
        JournalEvent(
            user_id=gm.id,
            partnership_id=partnership.id,
            type="quest_offered",
            visibility=JournalVisibility.SHARED,
            entity_type=None,
            entity_id=None,
            payload={},
        )
    )
    note(session, gm.id, "quest_declined", partnership.id)
    await session.commit()
    assert await codes(session, gm.id) == set()
    note(session, gm.id, "quest_offered", partnership.id)
    await session.commit()
    assert await codes(session, gm.id) == {"quest_giver"}


async def test_deleted_users_never_unlock(session: AsyncSession) -> None:
    gm, _, partnership = await pair(session)
    gm.deleted_at = clock.now()
    note(session, gm.id, "quest_offered", partnership.id)
    await session.commit()
    assert await codes(session, gm.id) == set()


async def test_concurrent_unlock_writes_one_row_and_one_event(
    independent_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with independent_sessions() as s:
        user = await factories.create_user(s, onboarded_at=clock.now())
        user_id = user.id
        await s.commit()

    first, second = independent_sessions(), independent_sessions()
    try:
        for s in (first, second):
            note(s, user_id, "quest_offered", None)
            await s.flush()
        await asyncio.gather(first.commit(), second.commit())
    finally:
        await first.close()
        await second.close()

    async with independent_sessions() as s:
        assert await codes(s, user_id) == {"quest_giver"}
        assert await unlock_events(s, user_id) == ["quest_giver"]


# --- GET /achievements -----------------------------------------------------------------------


async def test_get_achievements_lists_definitions_progress_and_unlocks(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    await complete(client, session, gm, player, gold=40)

    r = await client.get("/api/achievements", headers=auth(player))
    assert r.status_code == 200, r.text
    body = r.json()
    assert [d["code"] for d in body["definitions"]] == [a.code for a in ACHIEVEMENTS]
    defs = {d["code"]: d for d in body["definitions"]}
    assert defs["first_quest"]["progress"] == 1 and defs["first_quest"]["unlocked_at"]
    assert defs["quests_10"] == {
        "code": "quests_10",
        "icon": BY_CODE["quests_10"].icon,
        "target": 10,
        "progress": 1,
        "unlocked_at": None,
    }
    assert defs["gold_100"]["progress"] == 40
    assert defs["all_attributes"]["progress"] == 1
    assert [u["code"] for u in body["unlocks"]] == ["first_quest"]

    r = await client.get("/api/achievements", headers=auth(gm))
    assert [u["code"] for u in r.json()["unlocks"]] == ["quest_giver"]
    assert (await client.get("/api/achievements")).status_code == 401
