"""Pause and resume a recurring quest: creator only, stops and restarts generation."""

from datetime import date, timedelta
from types import ModuleType

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.jobs import generate_occurrences
from app.modules.common.enums import QuestOccurrenceStatus
from app.modules.journal.models import JournalEvent
from app.modules.notifications.models import Notification
from app.modules.quests.models import QuestOccurrence
from tests import factories
from tests.integration.completion_support import active_quest, auth, count, pair


@pytest.fixture(autouse=True)
def _clean_limiters() -> None:
    ratelimit.reset_all()


async def recurring(session: AsyncSession, gm, player, **terms) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    occurrence_id = await active_quest(session, gm, player, recurrence="daily", **terms)
    template_id = await session.scalar(
        select(QuestOccurrence.template_id).where(QuestOccurrence.id == occurrence_id)
    )
    assert template_id is not None
    return template_id, occurrence_id


async def dates(session: AsyncSession, template_id: int) -> list[date]:
    return list(
        await session.scalars(
            select(QuestOccurrence.scheduled_date)
            .where(QuestOccurrence.template_id == template_id)
            .order_by(QuestOccurrence.scheduled_date)
        )
    )


async def test_pause_stops_generation_and_resume_restarts_it_without_backfill(
    client: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    gm, player, _ = await pair(session)
    template_id, _ = await recurring(session, gm, player)

    paused = await client.post(f"/api/quest-templates/{template_id}/pause", headers=auth(gm))
    assert paused.status_code == 200, paused.text
    assert paused.json()["status"] == "paused"
    assert paused.json()["streak"] == {"current": 0, "best": 0, "last_completed_date": None}

    frozen_clock.advance(timedelta(days=3))
    assert await generate_occurrences.run(session) == 0
    assert await dates(session, template_id) == [date(2026, 1, 15)]

    resumed = await client.post(f"/api/quest-templates/{template_id}/resume", headers=auth(gm))
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "active"
    # Only the current period is created, right away; the three paused days stay empty.
    assert await dates(session, template_id) == [date(2026, 1, 15), date(2026, 1, 18)]
    assert resumed.json()["latest_occurrence"]["scheduled_date"] == "2026-01-18"

    frozen_clock.advance(timedelta(days=1))
    assert await generate_occurrences.run(session) == 1
    assert await dates(session, template_id) == [
        date(2026, 1, 15),
        date(2026, 1, 18),
        date(2026, 1, 19),
    ]


async def test_pause_and_resume_write_the_journal_and_notify_the_player(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    template_id, _ = await recurring(session, gm, player)
    assert (
        await client.post(f"/api/quest-templates/{template_id}/pause", headers=auth(gm))
    ).status_code == 200
    assert (
        await client.post(f"/api/quest-templates/{template_id}/resume", headers=auth(gm))
    ).status_code == 200
    types = set(
        await session.scalars(select(JournalEvent.type).where(JournalEvent.user_id == gm.id))
    )
    assert {"quest_paused", "quest_resumed"} <= types
    notified = set(
        await session.scalars(
            select(Notification.type).where(Notification.recipient_id == player.id)
        )
    )
    assert {"quest_paused", "quest_resumed"} <= notified


async def test_an_active_occurrence_stays_playable_while_paused(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    template_id, occurrence_id = await recurring(session, gm, player)
    await client.post(f"/api/quest-templates/{template_id}/pause", headers=auth(gm))
    submit = await client.post(f"/api/quests/{occurrence_id}/submit", headers=auth(player))
    assert submit.status_code == 200, submit.text
    occurrence = await session.get(QuestOccurrence, occurrence_id, populate_existing=True)
    assert occurrence is not None and occurrence.status == QuestOccurrenceStatus.IN_REVIEW


@pytest.mark.parametrize("action", ["pause", "resume"])
async def test_only_the_creator_may_pause_or_resume(
    client: httpx.AsyncClient, session: AsyncSession, action: str
) -> None:
    gm, player, _ = await pair(session)
    template_id, _ = await recurring(session, gm, player)
    if action == "resume":
        await client.post(f"/api/quest-templates/{template_id}/pause", headers=auth(gm))

    assert (
        await client.post(f"/api/quest-templates/{template_id}/{action}", headers=auth(player))
    ).status_code == 403
    stranger = await factories.create_user(session)
    assert (
        await client.post(f"/api/quest-templates/{template_id}/{action}", headers=auth(stranger))
    ).status_code == 404
    assert (await client.post(f"/api/quest-templates/{template_id}/{action}")).status_code == 401
    done = "paused" if action == "pause" else "resumed"
    assert await count(session, JournalEvent, JournalEvent.type == f"quest_{done}") == 0


async def test_invalid_states_are_409(client: httpx.AsyncClient, session: AsyncSession) -> None:
    gm, player, _ = await pair(session)
    template_id, _ = await recurring(session, gm, player)
    once_occurrence = await active_quest(session, gm, player, title="One-off")
    once_template = await session.scalar(
        select(QuestOccurrence.template_id).where(QuestOccurrence.id == once_occurrence)
    )
    url = f"/api/quest-templates/{template_id}"

    assert (await client.post(f"{url}/resume", headers=auth(gm))).status_code == 409  # not paused
    assert (await client.post(f"{url}/pause", headers=auth(gm))).status_code == 200
    assert (await client.post(f"{url}/pause", headers=auth(gm))).status_code == 409  # twice
    assert (await client.post(f"{url}/cancel", headers=auth(gm))).status_code == 200
    assert (await client.post(f"{url}/resume", headers=auth(gm))).status_code == 409  # cancelled

    response = await client.post(f"/api/quest-templates/{once_template}/pause", headers=auth(gm))
    assert response.status_code == 409


async def test_resume_with_a_deleted_assignee_creates_nothing(
    client: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    gm, player, _ = await pair(session)
    template_id, _ = await recurring(session, gm, player)
    await client.post(f"/api/quest-templates/{template_id}/pause", headers=auth(gm))
    player.deleted_at = frozen_clock.now()
    await session.commit()
    frozen_clock.advance(timedelta(days=1))
    response = await client.post(f"/api/quest-templates/{template_id}/resume", headers=auth(gm))
    assert response.status_code == 200
    assert await dates(session, template_id) == [date(2026, 1, 15)]
