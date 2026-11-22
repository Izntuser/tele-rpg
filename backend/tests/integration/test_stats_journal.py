"""S15 reads: GET /journal (scopes, keyset pagination, private events never shared), GET /stats
(counts, XP and quests per day, Gold earned/spent, rewards) and Life Balance (scores against
targets, suggestions, companion view, PUT only my own targets)."""

from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock, ratelimit
from app.modules.common.enums import JournalVisibility
from app.modules.journal.models import JournalEvent
from app.modules.journal.service import record_event
from app.modules.progression.models import XpTransaction
from app.modules.stats.models import LifeBalanceTarget
from app.modules.users.models import User
from tests import factories
from tests.integration.completion_support import active_quest, auth, count, pair


@pytest.fixture(autouse=True)
def _clean_limiters() -> None:
    ratelimit.reset_all()


async def get(client: httpx.AsyncClient, who: User | int, path: str, **params: Any) -> Any:
    r = await client.get(f"/api{path}", params=params, headers=auth(who))
    assert r.status_code == 200, r.text
    return r.json()


async def complete(
    client: httpx.AsyncClient, session: AsyncSession, gm: User, player: User, **terms: Any
) -> int:
    occ = await active_quest(session, gm, player, **terms)
    r = await client.post(f"/api/quests/{occ}/submit", headers=auth(player))
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/quests/{occ}/confirm", headers=auth(gm))
    assert r.status_code == 200, r.text
    return occ


async def backdate_xp(session: AsyncSession, occurrence_id: int, days: int) -> None:
    await session.execute(
        update(XpTransaction)
        .where(XpTransaction.quest_occurrence_id == occurrence_id)
        .values(created_at=clock.now() - timedelta(days=days))
    )
    await session.flush()


# --- journal ---------------------------------------------------------------------------------


async def test_journal_me_lists_my_events_newest_first(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    await complete(client, session, gm, player)

    mine = await get(client, player, "/journal", scope="me")
    types = [e["type"] for e in mine["items"]]
    assert "quest_completed" in types and "quest_accepted" in types
    assert "quest_offered" not in types  # the GM recorded that one
    assert all(e["actor"] == "me" for e in mine["items"])
    ids = [e["id"] for e in mine["items"]]
    assert ids == sorted(ids, reverse=True)
    completed = next(e for e in mine["items"] if e["type"] == "quest_completed")
    assert completed["payload"]["title"] == "Morning run"
    assert completed["entity_type"] == "quest_occurrence"


async def test_journal_shared_has_both_members_and_marks_the_actor(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    await complete(client, session, gm, player)

    shared = await get(client, gm, "/journal", scope="shared")
    actors = {(e["type"], e["actor"]) for e in shared["items"]}
    assert ("quest_offered", "me") in actors
    assert ("quest_completed", "companion") in actors
    assert ("quest_accepted", "companion") in actors


async def test_private_events_never_reach_the_companion(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, partnership = await pair(session)
    record_event(
        session,
        user_id=player.id,
        type="note_private",
        partnership_id=partnership.id,
        entity_type=None,
        entity_id=None,
        payload={"secret": 1},
        visibility=JournalVisibility.PRIVATE,
    )
    record_event(
        session,
        user_id=player.id,
        type="note_shared",
        partnership_id=partnership.id,
        entity_type=None,
        entity_id=None,
        payload={},
    )
    await session.flush()

    for scope in ("shared", "me"):
        seen = await get(client, gm, "/journal", scope=scope)
        assert "note_private" not in [e["type"] for e in seen["items"]]
    shared_gm = await get(client, gm, "/journal", scope="shared")
    assert "note_shared" in [e["type"] for e in shared_gm["items"]]
    # The owner sees it in their own journal, but not in the shared one either.
    mine = await get(client, player, "/journal", scope="me")
    assert "note_private" in [e["type"] for e in mine["items"]]
    shared_player = await get(client, player, "/journal", scope="shared")
    assert "note_private" not in [e["type"] for e in shared_player["items"]]


async def test_journal_cursor_pagination(client: httpx.AsyncClient, session: AsyncSession) -> None:
    _, player, partnership = await pair(session)
    for i in range(7):
        record_event(
            session,
            user_id=player.id,
            type="note",
            partnership_id=partnership.id,
            entity_type=None,
            entity_id=None,
            payload={"i": i},
        )
    await session.flush()

    seen: list[int] = []
    cursor: int | None = None
    pages = 0
    while True:
        params: dict[str, Any] = {"scope": "me", "limit": 3}
        if cursor is not None:
            params["cursor"] = cursor
        page = await get(client, player, "/journal", **params)
        pages += 1
        assert len(page["items"]) <= 3
        seen.extend(e["payload"]["i"] for e in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert pages == 3
    assert seen == list(range(6, -1, -1))


async def test_journal_without_partnership_and_bad_params(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    loner = await factories.create_user(session, onboarded_at=clock.now())
    assert await get(client, loner, "/journal", scope="shared") == {
        "items": [],
        "next_cursor": None,
    }
    for params in ({"scope": "all"}, {"cursor": 0}, {"limit": 0}, {"limit": 101}):
        r = await client.get("/api/journal", params=params, headers=auth(loner))
        assert r.status_code == 422, params
    assert (await client.get("/api/journal")).status_code == 401


async def test_ended_partnership_events_stay_in_my_journal_only(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    await complete(client, session, gm, player)
    r = await client.post(
        "/api/partnership/leave", json={"confirm_text": "LEAVE"}, headers=auth(player)
    )
    assert r.status_code == 204, r.text
    assert (await get(client, gm, "/journal", scope="shared"))["items"] == []
    mine = await get(client, player, "/journal", scope="me")
    assert "quest_completed" in [e["type"] for e in mine["items"]]


# --- stats -----------------------------------------------------------------------------------


async def test_stats_counts_xp_and_series(client: httpx.AsyncClient, session: AsyncSession) -> None:
    gm, player, _ = await pair(session)
    await complete(client, session, gm, player, difficulty="easy", gold=10)
    old = await complete(client, session, gm, player, difficulty="normal", gold=30)
    await backdate_xp(session, old, 10)

    week = await get(client, player, "/stats", period="7d")
    assert week["quests_completed"] == 1
    assert week["quests_completed_total"] == 2
    assert week["quests_completed_week"] == 1
    assert week["quests_completed_month"] == 2
    assert week["xp_total"] == 70
    assert week["xp_period"] == 20
    assert len(week["xp_per_day"]) == 7 and len(week["quests_per_day"]) == 7
    assert week["xp_per_day"][-1]["value"] == 20
    assert week["quests_per_day"][-1]["value"] == 1
    assert sum(d["value"] for d in week["xp_per_day"]) == 20
    # Gold is counted by ledger time (both rewards were paid now).
    assert week["gold_earned"] == 40 and week["gold_earned_total"] == 40
    assert week["gold_balance"] == 40

    month = await get(client, player, "/stats", period="30d")
    assert month["quests_completed"] == 2 and month["xp_period"] == 70
    assert len(month["xp_per_day"]) == 30
    assert sum(d["value"] for d in month["quests_per_day"]) == 2
    assert month["xp_per_day"][-11]["value"] == 50

    everything = await get(client, player, "/stats", period="all")
    assert everything["quests_completed"] == 2 and everything["xp_period"] == 70
    assert len(everything["xp_per_day"]) == 11
    assert everything["since"] == everything["xp_per_day"][0]["date"]

    # The GM completed nothing.
    gm_stats = await get(client, gm, "/stats", period="all")
    assert gm_stats["quests_completed_total"] == 0 and gm_stats["xp_total"] == 0
    assert gm_stats["xp_per_day"] == [{"date": gm_stats["since"], "value": 0}]


async def test_stats_gold_spent_and_rewards(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    await complete(client, session, gm, player, gold=300)
    rewards = []
    for title in ("Massage", "Movie night"):
        r = await client.post("/api/rewards", json={"title": title, "price": 100}, headers=auth(gm))
        assert r.status_code == 201, r.text
        rewards.append(r.json()["id"])
    purchases = []
    for i, reward_id in enumerate(rewards):
        r = await client.post(
            f"/api/rewards/{reward_id}/purchase",
            headers=auth(player, **{"Idempotency-Key": f"stats-{i}"}),
        )
        assert r.status_code == 201, r.text
        purchases.append(r.json()["id"])
    # Refund the second, fulfil the first.
    r = await client.post(f"/api/inventory/{purchases[1]}/refund", headers=auth(player))
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/inventory/{purchases[0]}/request", headers=auth(player))
    assert r.status_code == 200, r.text
    r = await client.post(
        f"/api/inventory/{purchases[0]}/schedule",
        json={"scheduled_for": (clock.now() + timedelta(days=1)).isoformat()},
        headers=auth(gm),
    )
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/inventory/{purchases[0]}/fulfill", headers=auth(gm))
    assert r.status_code == 200, r.text

    stats = await get(client, player, "/stats", period="7d")
    assert stats["gold_earned"] == 300
    assert stats["gold_spent"] == 100
    assert stats["gold_spent_total"] == 100
    assert stats["gold_balance"] == 200
    assert stats["rewards_purchased"] == 1
    assert stats["rewards_fulfilled"] == 1


async def test_stats_period_validation(client: httpx.AsyncClient, session: AsyncSession) -> None:
    user = await factories.create_user(session, onboarded_at=clock.now())
    r = await client.get("/api/stats", params={"period": "1y"}, headers=auth(user))
    assert r.status_code == 422
    assert (await client.get("/api/stats")).status_code == 401


async def test_stats_use_my_timezone_for_days(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    player.timezone = "Pacific/Kiritimati"  # UTC+14
    await session.flush()
    await complete(client, session, gm, player)
    stats = await get(client, player, "/stats", period="7d")
    local_today = clock.now().astimezone(__import__("zoneinfo").ZoneInfo("Pacific/Kiritimati"))
    assert stats["xp_per_day"][-1]["date"] == local_today.date().isoformat()
    assert stats["xp_per_day"][-1]["value"] == 50


# --- life balance ----------------------------------------------------------------------------


def by_attribute(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {a["attribute"]: a for a in body["attributes"]}


async def test_life_balance_scores_against_default_targets(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    await complete(client, session, gm, player, attribute="physical", difficulty="normal")
    await complete(client, session, gm, player, attribute="physical", difficulty="hard")
    await complete(client, session, gm, player, attribute="social", difficulty="easy")

    body = await get(client, player, "/stats/life-balance", period="7d")
    assert body["period"] == "7d" and body["user"] == "me"
    scores = by_attribute(body)
    assert list(scores) == [
        "physical",
        "intellectual",
        "discipline",
        "social",
        "creativity",
        "wellbeing",
    ]
    assert scores["physical"] == {
        "attribute": "physical",
        "earned_xp": 150,
        "weekly_target": 100,
        "period_target": 100,
        "score": 100,
    }
    assert scores["social"]["score"] == 20
    assert scores["creativity"]["score"] == 0
    assert body["balanced"] is False
    assert [(s["attribute"], s["reason"]) for s in body["suggestions"]] == [
        ("intellectual", "no_activity"),
        ("discipline", "no_activity"),
        ("creativity", "no_activity"),
    ]

    month = await get(client, player, "/stats/life-balance", period="30d")
    assert by_attribute(month)["physical"]["period_target"] == 429
    assert by_attribute(month)["physical"]["score"] == 34


async def test_life_balance_window_excludes_old_xp(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    occ = await complete(client, session, gm, player, attribute="creativity")
    await backdate_xp(session, occ, 10)
    week = by_attribute(await get(client, player, "/stats/life-balance", period="7d"))
    month = by_attribute(await get(client, player, "/stats/life-balance", period="30d"))
    assert week["creativity"]["earned_xp"] == 0
    assert month["creativity"]["earned_xp"] == 50


async def test_companion_life_balance_and_unpaired_403(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    await complete(client, session, gm, player, attribute="wellbeing")
    seen = await get(client, gm, "/stats/life-balance", period="7d", user="companion")
    assert seen["user"] == "companion"
    assert by_attribute(seen)["wellbeing"]["earned_xp"] == 50
    own = await get(client, gm, "/stats/life-balance", period="7d", user="me")
    assert by_attribute(own)["wellbeing"]["earned_xp"] == 0

    loner = await factories.create_user(session, onboarded_at=clock.now())
    r = await client.get(
        "/api/stats/life-balance", params={"user": "companion"}, headers=auth(loner)
    )
    assert r.status_code == 403
    for params in ({"period": "all"}, {"user": "someone"}):
        r = await client.get("/api/stats/life-balance", params=params, headers=auth(loner))
        assert r.status_code == 422, params


async def test_put_targets_changes_only_my_own(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    defaults = await get(client, player, "/stats/life-balance/targets")
    assert defaults["targets"] == {a: 100 for a in by_attribute_order()}

    r = await client.put(
        "/api/stats/life-balance/targets",
        json={"targets": {"physical": 50, "creativity": 0}},
        headers=auth(player),
    )
    assert r.status_code == 200, r.text
    assert r.json()["targets"]["physical"] == 50
    assert r.json()["targets"]["creativity"] == 0
    assert r.json()["targets"]["social"] == 100
    # Update again (upsert), other attributes keep their value.
    r = await client.put(
        "/api/stats/life-balance/targets",
        json={"targets": {"physical": 70}},
        headers=auth(player),
    )
    assert r.json()["targets"]["physical"] == 70
    assert r.json()["targets"]["creativity"] == 0

    assert await count(session, LifeBalanceTarget, LifeBalanceTarget.user_id == gm.id) == 0
    gm_targets = await get(client, gm, "/stats/life-balance/targets")
    assert set(gm_targets["targets"].values()) == {100}

    # The companion sees the scores against the owner's targets.
    await complete(client, session, gm, player, attribute="physical", difficulty="normal")
    seen = by_attribute(await get(client, gm, "/stats/life-balance", user="companion"))
    assert seen["physical"]["weekly_target"] == 70 and seen["physical"]["score"] == 71
    assert seen["creativity"]["score"] == 100


@pytest.mark.parametrize(
    "body",
    [
        {"targets": {}},
        {"targets": {"physical": -1}},
        {"targets": {"physical": 10_001}},
        {"targets": {"strength": 10}},
        {"targets": {"physical": "lots"}},
        {},
    ],
)
async def test_put_targets_validation(
    client: httpx.AsyncClient, session: AsyncSession, body: dict[str, Any]
) -> None:
    user = await factories.create_user(session, onboarded_at=clock.now())
    r = await client.put("/api/stats/life-balance/targets", json=body, headers=auth(user))
    assert r.status_code == 422, r.text
    assert await count(session, LifeBalanceTarget) == 0


async def test_targets_cannot_name_another_user(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    r = await client.put(
        "/api/stats/life-balance/targets",
        json={"targets": {"physical": 5}, "user_id": gm.id, "user": "companion"},
        headers=auth(player),
    )
    assert r.status_code == 200
    assert await count(session, LifeBalanceTarget, LifeBalanceTarget.user_id == gm.id) == 0
    assert await count(session, LifeBalanceTarget, LifeBalanceTarget.user_id == player.id) == 1


def by_attribute_order() -> list[str]:
    return ["physical", "intellectual", "discipline", "social", "creativity", "wellbeing"]


async def test_journal_events_counted_for_unlock_are_shared(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """Sanity: the journal rows behind the stats are shared, so the companion's view has them."""
    gm, player, _ = await pair(session)
    await complete(client, session, gm, player)
    shared = await count(session, JournalEvent, JournalEvent.visibility == JournalVisibility.SHARED)
    assert shared >= 4
