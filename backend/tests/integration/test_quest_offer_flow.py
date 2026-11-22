"""Quest offer flow over HTTP (create, edit, revisions, accept, decline, cancel, lists), plus
the transactional journal/notification guarantees and concurrency on one quest."""

import asyncio
from datetime import date, datetime, timedelta
from types import ModuleType
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import clock, ratelimit
from app.core.config import get_settings
from app.modules.auth.jwt import encode_token
from app.modules.common.enums import (
    Attribute,
    Difficulty,
    NotificationCategory,
    NotificationStatus,
    PartnershipStatus,
    QuestOccurrenceStatus,
    QuestRevisionStatus,
    QuestTemplateStatus,
    Recurrence,
)
from app.modules.journal.models import JournalEvent
from app.modules.journal.service import PayloadNameError, check_payload, record_event
from app.modules.notifications.models import Notification
from app.modules.notifications.service import enqueue
from app.modules.partnerships.models import Partnership
from app.modules.quests import service
from app.modules.quests.models import QuestOccurrence, QuestRevision, QuestTemplate
from app.modules.quests.occurrences import (
    TemplateNotSchedulableError,
    ensure_occurrence,
    period_start,
    recurring_due_at,
)
from app.modules.quests.schemas import QuestCreate
from app.modules.users.models import User
from tests import factories

# FROZEN_AT (conftest) is Thursday 2026-01-15 12:00 UTC.
THURSDAY = date(2026, 1, 15)
MONDAY = date(2026, 1, 12)


@pytest.fixture(autouse=True)
def _clean_limiters() -> None:
    ratelimit.reset_all()


def auth(user: User) -> dict[str, str]:
    token = encode_token(user.id, get_settings().jwt_secret.get_secret_value(), timedelta(hours=1))
    return {"Authorization": f"Bearer {token}"}


async def pair(session: AsyncSession, *, player_tz: str = "UTC") -> tuple[User, User, Partnership]:
    """(game master, player, their active partnership)."""
    gm = await factories.create_user(session, onboarded_at=clock.now())
    player = await factories.create_user(session, onboarded_at=clock.now(), timezone=player_tz)
    return gm, player, await factories.create_partnership(session, gm, player)


def quest_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "title": "Morning run",
        "description": "5 km",
        "attribute": "physical",
        "difficulty": "normal",
        "gold": 50,
    }
    body.update(overrides)
    return body


async def create_quest(client: httpx.AsyncClient, gm: User, **overrides: Any) -> dict[str, Any]:
    response = await client.post("/api/quests", headers=auth(gm), json=quest_body(**overrides))
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


async def post(
    client: httpx.AsyncClient, user: User, path: str, body: dict[str, Any] | None = None
) -> httpx.Response:
    return await client.post(f"/api{path}", headers=auth(user), json=body)


async def counts(session: AsyncSession) -> tuple[int, int]:
    journal = await session.scalar(select(func.count()).select_from(JournalEvent))
    notes = await session.scalar(select(func.count()).select_from(Notification))
    return journal or 0, notes or 0


# --- create ----------------------------------------------------------------------------------


async def test_create_once_offers_an_occurrence_to_the_partner(
    client: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    gm, player, partnership = await pair(session, player_tz="Pacific/Kiritimati")
    deadline = (clock.now() + timedelta(days=2)).isoformat()
    created = await create_quest(client, gm, xp=9999, difficulty="hard", deadline_at=deadline)

    template, occurrence = created["template"], created["occurrence"]
    assert template["status"] == "offered"
    assert template["creator_id"] == gm.id and template["assignee_id"] == player.id
    assert template["partnership_id"] == partnership.id
    assert template["role"] == "gm" and template["version"] == 1
    assert template["terms"]["xp"] == 100  # Settings.difficulty_xp[hard]; client xp ignored
    assert occurrence["status"] == "offered"
    assert occurrence["assignee_id"] == player.id
    assert occurrence["terms"] == template["terms"]
    # UTC+14: 12:00 UTC Thursday is already Friday for the assignee.
    assert occurrence["scheduled_date"] == "2026-01-16"
    assert datetime.fromisoformat(occurrence["due_at"]) == datetime.fromisoformat(deadline)

    revision = await session.scalar(
        select(QuestRevision).where(QuestRevision.template_id == template["id"])
    )
    assert revision is not None
    assert revision.version == 1 and revision.status == QuestRevisionStatus.PENDING
    assert revision.terms["xp"] == 100
    db_template = await session.get(QuestTemplate, template["id"])
    assert db_template is not None and db_template.current_revision_id == revision.id


async def test_create_recurring_offers_the_template_with_revision_1_only(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    created = await create_quest(client, gm, recurrence="daily", difficulty="easy")
    assert created["occurrence"] is None
    template = created["template"]
    assert template["status"] == "offered" and template["recurrence"] == "daily"
    assert template["terms"]["xp"] == 20
    occurrences = await session.scalar(
        select(func.count())
        .select_from(QuestOccurrence)
        .where(QuestOccurrence.template_id == template["id"])
    )
    assert occurrences == 0
    revisions = list(
        await session.scalars(
            select(QuestRevision).where(QuestRevision.template_id == template["id"])
        )
    )
    assert [(r.version, r.status) for r in revisions] == [(1, QuestRevisionStatus.PENDING)]


@pytest.mark.parametrize(
    "overrides",
    [
        {"gold": -1},
        {"gold": 1001},
        {"gold": "lots"},
        {"recurrence": "daily", "deadline_at": "2099-01-01T00:00:00Z"},
        {"recurrence": "weekly", "deadline_at": "2099-01-01T00:00:00Z"},
        {"deadline_at": "2020-01-01T00:00:00Z"},
        {"deadline_at": "2099-01-01T00:00:00"},  # naive
        {"title": "   "},
        {"title": "x" * 201},
        {"attribute": "magic"},
        {"difficulty": "legendary"},
        {"recurrence": "monthly"},
    ],
)
async def test_create_rejects_invalid_terms(
    client: httpx.AsyncClient, session: AsyncSession, overrides: dict[str, Any]
) -> None:
    gm, _, _ = await pair(session)
    response = await client.post("/api/quests", headers=auth(gm), json=quest_body(**overrides))
    assert response.status_code == 422, response.text
    assert await session.scalar(select(func.count()).select_from(QuestTemplate)) == 0


async def test_create_accepts_gold_bounds(client: httpx.AsyncClient, session: AsyncSession) -> None:
    gm, _, _ = await pair(session)
    for gold in (0, 1000):
        created = await create_quest(client, gm, gold=gold)
        assert created["template"]["terms"]["gold"] == gold


async def test_create_ignores_client_identity_and_status_fields(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    stranger = await factories.create_user(session)
    created = await create_quest(
        client,
        gm,
        assignee_id=stranger.id,
        creator_id=stranger.id,
        status="active",
        partnership_id=999,
    )
    assert created["template"]["assignee_id"] == player.id
    assert created["template"]["creator_id"] == gm.id
    assert created["template"]["status"] == "offered"


async def test_create_without_partnership_is_403(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    loner = await factories.create_user(session, onboarded_at=clock.now())
    response = await client.post("/api/quests", headers=auth(loner), json=quest_body())
    assert response.status_code == 403
    other, ended_partner = (
        await factories.create_user(session),
        await factories.create_user(session),
    )
    await factories.create_partnership(
        session, other, ended_partner, status=PartnershipStatus.ENDED
    )
    response = await client.post("/api/quests", headers=auth(other), json=quest_body())
    assert response.status_code == 403


async def test_create_caps_open_quests_per_creator(
    client: httpx.AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "MAX_OPEN_TEMPLATES", 2)
    gm, _, _ = await pair(session)
    await create_quest(client, gm)
    await create_quest(client, gm)
    response = await client.post("/api/quests", headers=auth(gm), json=quest_body())
    assert response.status_code == 409


# --- accept / decline ------------------------------------------------------------------------


async def test_accept_once_offer(
    client: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    gm, player, _ = await pair(session)
    occurrence_id = (await create_quest(client, gm))["occurrence"]["id"]
    response = await post(client, player, f"/quests/{occurrence_id}/accept")
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["status"] == "active"
    assert detail["template_status"] == "active"
    assert detail["role"] == "player"
    assert datetime.fromisoformat(detail["accepted_at"]) == clock.now()
    assert detail["template"]["pending_revision"] is None
    revision = await session.scalar(
        select(QuestRevision).where(QuestRevision.template_id == detail["template_id"])
    )
    assert revision is not None and revision.status == QuestRevisionStatus.ACCEPTED
    assert revision.decided_at == clock.now()
    # Accepting twice is a state conflict.
    again = await post(client, player, f"/quests/{occurrence_id}/accept")
    assert again.status_code == 409


@pytest.mark.parametrize(
    ("recurrence", "tz", "scheduled", "due"),
    [
        ("daily", "UTC", THURSDAY, datetime.fromisoformat("2026-01-16T00:00:00+00:00")),
        ("weekly", "UTC", MONDAY, datetime.fromisoformat("2026-01-19T00:00:00+00:00")),
        (
            "daily",
            "Pacific/Kiritimati",
            date(2026, 1, 16),
            datetime.fromisoformat("2026-01-17T00:00:00+14:00"),
        ),
    ],
)
async def test_accept_recurring_offer_activates_and_creates_todays_occurrence(
    client: httpx.AsyncClient,
    session: AsyncSession,
    frozen_clock: ModuleType,
    recurrence: str,
    tz: str,
    scheduled: date,
    due: datetime,
) -> None:
    gm, player, _ = await pair(session, player_tz=tz)
    template_id = (await create_quest(client, gm, recurrence=recurrence))["template"]["id"]
    response = await post(client, player, f"/quest-templates/{template_id}/accept")
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["status"] == "active"
    occurrence = detail["latest_occurrence"]
    assert occurrence["status"] == "active"
    assert occurrence["scheduled_date"] == scheduled.isoformat()
    assert datetime.fromisoformat(occurrence["due_at"]) == due
    assert occurrence["terms"] == detail["terms"]
    assert datetime.fromisoformat(occurrence["accepted_at"]) == clock.now()

    template = await session.get(QuestTemplate, template_id)
    assert template is not None
    again, created = await ensure_occurrence(session, template, tz)
    assert created is False and again.id == occurrence["id"]
    count = await session.scalar(
        select(func.count())
        .select_from(QuestOccurrence)
        .where(QuestOccurrence.template_id == template_id)
    )
    assert count == 1


async def test_ensure_occurrence_creates_the_next_period_and_refuses_unschedulable(
    client: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    gm, player, _ = await pair(session)
    template_id = (await create_quest(client, gm, recurrence="daily"))["template"]["id"]
    template = await session.get(QuestTemplate, template_id)
    assert template is not None
    with pytest.raises(TemplateNotSchedulableError):
        await ensure_occurrence(session, template, "UTC")  # still offered
    await post(client, player, f"/quest-templates/{template_id}/accept")
    await session.refresh(template)
    tomorrow, created = await ensure_occurrence(session, template, "UTC", on=date(2026, 1, 16))
    assert created and tomorrow.status == QuestOccurrenceStatus.ACTIVE
    assert tomorrow.scheduled_date == date(2026, 1, 16)
    template.status = QuestTemplateStatus.PAUSED
    with pytest.raises(TemplateNotSchedulableError):
        await ensure_occurrence(session, template, "UTC", on=date(2026, 1, 17))


def test_period_and_due_helpers() -> None:
    assert period_start(Recurrence.WEEKLY, date(2026, 1, 18)) == MONDAY  # Sunday
    assert period_start(Recurrence.WEEKLY, MONDAY) == MONDAY
    assert period_start(Recurrence.DAILY, THURSDAY) == THURSDAY
    assert recurring_due_at(Recurrence.ONCE, THURSDAY, "UTC") is None
    # DST: Europe/Kyiv switches on 2026-03-29; the next local midnight is 21:00 UTC.
    assert recurring_due_at(Recurrence.DAILY, date(2026, 3, 29), "Europe/Kyiv") == (
        datetime.fromisoformat("2026-03-29T21:00:00+00:00")
    )


async def test_decline_once_offer_with_reason(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    occurrence_id = (await create_quest(client, gm))["occurrence"]["id"]
    response = await post(
        client, player, f"/quests/{occurrence_id}/decline", {"reason": "  Too far  "}
    )
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["status"] == "declined" and detail["template_status"] == "declined"
    assert detail["decline_reason"] == "Too far"
    note = await session.scalar(select(Notification).where(Notification.type == "quest_declined"))
    assert note is not None and note.recipient_id == gm.id
    assert "Too far" not in str(note.payload)
    assert (await post(client, player, f"/quests/{occurrence_id}/accept")).status_code == 409


async def test_decline_without_body_and_recurring_decline_keeps_reason_on_revision(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    occurrence_id = (await create_quest(client, gm))["occurrence"]["id"]
    response = await client.post(f"/api/quests/{occurrence_id}/decline", headers=auth(player))
    assert response.status_code == 200
    assert response.json()["decline_reason"] is None

    template_id = (await create_quest(client, gm, recurrence="weekly"))["template"]["id"]
    response = await post(
        client, player, f"/quest-templates/{template_id}/decline", {"reason": "Busy"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "declined"
    revision = await session.scalar(
        select(QuestRevision).where(QuestRevision.template_id == template_id)
    )
    assert revision is not None
    assert revision.status == QuestRevisionStatus.DECLINED and revision.decline_reason == "Busy"
    long_reason = await post(
        client, player, f"/quest-templates/{template_id}/decline", {"reason": "x" * 501}
    )
    assert long_reason.status_code == 422


# --- cancel ----------------------------------------------------------------------------------


async def test_either_party_cancels_offered_or_active(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    first = (await create_quest(client, gm))["occurrence"]["id"]
    response = await post(client, gm, f"/quests/{first}/cancel")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled" and body["template_status"] == "cancelled"
    assert body["cancelled_by"] == gm.id

    second = (await create_quest(client, gm))["occurrence"]["id"]
    await post(client, player, f"/quests/{second}/accept")
    response = await post(client, player, f"/quests/{second}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["cancelled_by"] == player.id
    assert (await post(client, gm, f"/quests/{second}/cancel")).status_code == 409


async def test_in_review_and_terminal_occurrences_cannot_be_cancelled(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    occurrence_id = (await create_quest(client, gm))["occurrence"]["id"]
    await post(client, player, f"/quests/{occurrence_id}/accept")
    occurrence = await session.get(QuestOccurrence, occurrence_id)
    assert occurrence is not None
    occurrence.status = QuestOccurrenceStatus.IN_REVIEW
    await session.flush()
    response = await post(client, gm, f"/quests/{occurrence_id}/cancel")
    assert response.status_code == 409
    assert "in_review" in response.json()["detail"]
    template_id = occurrence.template_id
    assert (await post(client, gm, f"/quest-templates/{template_id}/cancel")).status_code == 409


async def test_cancelling_a_recurring_template_cancels_open_occurrences_only(
    client: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    gm, player, _ = await pair(session)
    template_id = (await create_quest(client, gm, recurrence="daily"))["template"]["id"]
    accepted = await post(client, player, f"/quest-templates/{template_id}/accept")
    today_id = accepted.json()["latest_occurrence"]["id"]
    template = await session.get(QuestTemplate, template_id)
    assert template is not None
    review, _ = await ensure_occurrence(session, template, "UTC", on=date(2026, 1, 14))
    review.status = QuestOccurrenceStatus.IN_REVIEW
    await session.flush()

    # Cancelling one occurrence of a recurring quest leaves the quest running.
    response = await post(client, player, f"/quests/{today_id}/cancel")
    assert response.status_code == 200
    assert response.json()["template_status"] == "active"

    tomorrow, _ = await ensure_occurrence(session, template, "UTC", on=date(2026, 1, 16))
    response = await post(client, gm, f"/quest-templates/{template_id}/cancel")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"
    statuses = dict(
        (
            await session.execute(
                select(QuestOccurrence.id, QuestOccurrence.status)
                .where(QuestOccurrence.template_id == template_id)
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    assert statuses == {
        today_id: QuestOccurrenceStatus.CANCELLED,
        review.id: QuestOccurrenceStatus.IN_REVIEW,
        tomorrow.id: QuestOccurrenceStatus.CANCELLED,
    }


async def test_cancelling_a_recurring_offer(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    template_id = (await create_quest(client, gm, recurrence="daily"))["template"]["id"]
    response = await post(client, player, f"/quest-templates/{template_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    revision = await session.scalar(
        select(QuestRevision)
        .where(QuestRevision.template_id == template_id)
        .execution_options(populate_existing=True)
    )
    assert revision is not None and revision.status == QuestRevisionStatus.SUPERSEDED
    assert (await post(client, player, f"/quest-templates/{template_id}/accept")).status_code == 409


# --- edit / revisions ------------------------------------------------------------------------


async def test_patch_while_offered_edits_in_place(
    client: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    gm, player, _ = await pair(session)
    occurrence_id = (await create_quest(client, gm))["occurrence"]["id"]
    deadline = (clock.now() + timedelta(days=3)).isoformat()
    response = await client.patch(
        f"/api/quests/{occurrence_id}",
        headers=auth(gm),
        json={"title": "Evening run", "difficulty": "epic", "deadline_at": deadline, "xp": 1},
    )
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["status"] == "offered"
    assert detail["terms"]["title"] == "Evening run"
    assert detail["terms"]["xp"] == 250
    assert detail["terms"]["description"] == "5 km"  # untouched
    assert datetime.fromisoformat(detail["due_at"]) == datetime.fromisoformat(deadline)
    assert detail["template"]["terms"] == detail["terms"]
    assert detail["template"]["version"] == 1
    assert detail["template"]["pending_revision"] is None
    template = await session.get(QuestTemplate, detail["template_id"])
    assert template is not None
    assert template.title == "Evening run" and template.difficulty == Difficulty.EPIC
    revisions = await session.scalar(
        select(func.count())
        .select_from(QuestRevision)
        .where(QuestRevision.template_id == template.id)
    )
    assert revisions == 1
    note = await session.scalar(
        select(Notification).where(Notification.type == "quest_offer_updated")
    )
    assert note is not None and note.recipient_id == player.id
    # Clearing the description and the deadline.
    response = await client.patch(
        f"/api/quests/{occurrence_id}",
        headers=auth(gm),
        json={"description": None, "deadline_at": None},
    )
    assert response.json()["terms"]["description"] is None
    assert response.json()["due_at"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"title": None},
        {"gold": None},
        {"gold": 1001},
        {"deadline_at": "2020-01-01T00:00:00Z"},
        {"title": ""},
    ],
)
async def test_patch_rejects_invalid_values(
    client: httpx.AsyncClient, session: AsyncSession, body: dict[str, Any]
) -> None:
    gm, _, _ = await pair(session)
    occurrence_id = (await create_quest(client, gm))["occurrence"]["id"]
    response = await client.patch(f"/api/quests/{occurrence_id}", headers=auth(gm), json=body)
    assert response.status_code == 422, response.text


async def test_patch_deadline_on_recurring_is_422(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, _, _ = await pair(session)
    template_id = (await create_quest(client, gm, recurrence="daily"))["template"]["id"]
    response = await client.patch(
        f"/api/quest-templates/{template_id}",
        headers=auth(gm),
        json={"deadline_at": "2099-01-01T00:00:00Z"},
    )
    assert response.status_code == 422


async def test_revision_on_active_recurring_quest_applies_to_future_occurrences_only(
    client: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    gm, player, _ = await pair(session)
    template_id = (await create_quest(client, gm, recurrence="daily", gold=10))["template"]["id"]
    accepted = (await post(client, player, f"/quest-templates/{template_id}/accept")).json()
    today = accepted["latest_occurrence"]

    response = await client.patch(
        f"/api/quest-templates/{template_id}", headers=auth(gm), json={"gold": 20}
    )
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["terms"]["gold"] == 10  # unchanged until the assignee accepts
    assert detail["pending_revision"]["version"] == 2
    assert detail["pending_revision"]["terms"]["gold"] == 20
    assert detail["pending_revision"]["proposed_by"] == gm.id

    # A newer proposal supersedes the pending one.
    response = await client.patch(f"/api/quests/{today['id']}", headers=auth(gm), json={"gold": 30})
    assert response.status_code == 200
    assert response.json()["has_pending_revision"] is True
    assert response.json()["template"]["pending_revision"]["version"] == 3
    statuses = dict(
        (
            await session.execute(
                select(QuestRevision.version, QuestRevision.status).where(
                    QuestRevision.template_id == template_id
                )
            )
        ).all()
    )
    assert statuses == {
        1: QuestRevisionStatus.ACCEPTED,
        2: QuestRevisionStatus.SUPERSEDED,
        3: QuestRevisionStatus.PENDING,
    }
    # Proposing the same terms again is a no-op.
    await client.patch(f"/api/quest-templates/{template_id}", headers=auth(gm), json={"gold": 30})
    assert (
        await session.scalar(
            select(func.max(QuestRevision.version)).where(QuestRevision.template_id == template_id)
        )
        == 3
    )

    response = await post(client, player, f"/quests/{today['id']}/accept")
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["terms"]["gold"] == 10  # the existing snapshot stays
    assert detail["template"]["terms"]["gold"] == 30
    assert detail["template"]["version"] == 3
    assert detail["template"]["pending_revision"] is None
    template = await session.get(QuestTemplate, template_id)
    assert template is not None and template.gold == 30
    tomorrow, _ = await ensure_occurrence(session, template, "UTC", on=date(2026, 1, 16))
    assert tomorrow.terms_snapshot["gold"] == 30
    unchanged = await session.get(QuestOccurrence, today["id"], populate_existing=True)
    assert unchanged is not None and unchanged.terms_snapshot["gold"] == 10
    assert (await post(client, player, f"/quests/{today['id']}/accept")).status_code == 409


async def test_declined_revision_leaves_terms(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    template_id = (await create_quest(client, gm, recurrence="weekly"))["template"]["id"]
    await post(client, player, f"/quest-templates/{template_id}/accept")
    await client.patch(
        f"/api/quest-templates/{template_id}", headers=auth(gm), json={"title": "Swim"}
    )
    response = await post(
        client, player, f"/quest-templates/{template_id}/decline", {"reason": "No pool"}
    )
    assert response.status_code == 200
    detail = response.json()
    assert detail["status"] == "active"
    assert detail["terms"]["title"] == "Morning run"
    assert detail["pending_revision"] is None
    revision = await session.scalar(
        select(QuestRevision).where(
            QuestRevision.template_id == template_id, QuestRevision.version == 2
        )
    )
    assert revision is not None
    assert revision.status == QuestRevisionStatus.DECLINED
    assert revision.decline_reason == "No pool"
    assert (
        await post(client, player, f"/quest-templates/{template_id}/decline")
    ).status_code == 409


async def test_revision_on_active_once_quest_updates_its_occurrence(
    client: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    """DECISIONS #15: a one-time quest has no future occurrence, so an accepted revision
    applies to its single occurrence while that is still active."""
    gm, player, _ = await pair(session)
    occurrence_id = (await create_quest(client, gm))["occurrence"]["id"]
    await post(client, player, f"/quests/{occurrence_id}/accept")
    deadline = (clock.now() + timedelta(days=1)).isoformat()
    response = await client.patch(
        f"/api/quests/{occurrence_id}",
        headers=auth(gm),
        json={"gold": 70, "deadline_at": deadline},
    )
    assert response.status_code == 200
    assert response.json()["terms"]["gold"] == 50
    assert response.json()["has_pending_revision"] is True
    response = await post(client, player, f"/quests/{occurrence_id}/accept")
    assert response.status_code == 200
    detail = response.json()
    assert detail["status"] == "active"
    assert detail["terms"]["gold"] == 70
    assert datetime.fromisoformat(detail["due_at"]) == datetime.fromisoformat(deadline)


async def test_patch_is_refused_in_closed_states(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    declined = (await create_quest(client, gm))["occurrence"]["id"]
    await post(client, player, f"/quests/{declined}/decline")
    response = await client.patch(f"/api/quests/{declined}", headers=auth(gm), json={"gold": 1})
    assert response.status_code == 409

    in_review = (await create_quest(client, gm))["occurrence"]["id"]
    await post(client, player, f"/quests/{in_review}/accept")
    occurrence = await session.get(QuestOccurrence, in_review)
    assert occurrence is not None
    occurrence.status = QuestOccurrenceStatus.IN_REVIEW
    await session.flush()
    response = await client.patch(f"/api/quests/{in_review}", headers=auth(gm), json={"gold": 1})
    assert response.status_code == 409


# --- lists -----------------------------------------------------------------------------------


async def test_list_tabs(client: httpx.AsyncClient, session: AsyncSession) -> None:
    gm, player, _ = await pair(session)
    offered = (await create_quest(client, gm))["occurrence"]["id"]
    active = (await create_quest(client, gm))["occurrence"]["id"]
    await post(client, player, f"/quests/{active}/accept")
    review = (await create_quest(client, gm))["occurrence"]["id"]
    await post(client, player, f"/quests/{review}/accept")
    row = await session.get(QuestOccurrence, review)
    assert row is not None
    row.status = QuestOccurrenceStatus.IN_REVIEW
    mine = (await create_quest(client, player))["occurrence"]["id"]  # player as GM
    await session.flush()

    async def ids(user: User, query: str) -> list[int]:
        response = await client.get(f"/api/quests?{query}", headers=auth(user))
        assert response.status_code == 200, response.text
        return [item["id"] for item in response.json()]

    assert await ids(player, "role=player&status=offered") == [offered]
    assert await ids(player, "role=player&status=active") == [active]
    assert await ids(player, "role=player&status=active&status=in_review") == [review, active]
    assert await ids(player, "role=gm") == [mine]
    assert await ids(gm, "role=gm&status=in_review") == [review]
    assert await ids(gm, "role=gm") == [review, active, offered]
    assert await ids(gm, "role=player&status=offered") == [mine]
    assert await ids(gm, "") == [mine, review, active, offered]
    assert await ids(gm, "limit=2") == [mine, review]
    items = (await client.get("/api/quests?role=player", headers=auth(player))).json()
    assert {i["role"] for i in items} == {"player"}
    bad = await client.get("/api/quests?status=bogus", headers=auth(gm))
    assert bad.status_code == 422
    assert (await client.get("/api/quests?role=boss", headers=auth(gm))).status_code == 422
    assert (await client.get("/api/quests?limit=0", headers=auth(gm))).status_code == 422


async def test_template_list_shows_recurring_offers(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    daily = (await create_quest(client, gm, recurrence="daily"))["template"]["id"]
    once = (await create_quest(client, gm))["template"]["id"]
    response = await client.get(
        "/api/quest-templates?role=player&status=offered&recurrence=daily", headers=auth(player)
    )
    assert [t["id"] for t in response.json()] == [daily]
    response = await client.get("/api/quest-templates?role=gm", headers=auth(gm))
    assert [t["id"] for t in response.json()] == [once, daily]
    await post(client, player, f"/quest-templates/{daily}/accept")
    await client.patch(f"/api/quest-templates/{daily}", headers=auth(gm), json={"gold": 1})
    response = await client.get("/api/quest-templates?status=active", headers=auth(player))
    [item] = response.json()
    assert item["pending_revision"]["terms"]["gold"] == 1


async def test_lists_are_empty_without_an_active_partnership(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    loner = await factories.create_user(session)
    assert (await client.get("/api/quests", headers=auth(loner))).json() == []
    assert (await client.get("/api/quest-templates", headers=auth(loner))).json() == []


# --- journal and notifications ---------------------------------------------------------------


async def test_each_transition_writes_one_journal_event_and_one_notification(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, partnership = await pair(session)
    steps: list[tuple[User, str, str, int]] = []

    occurrence_id = (await create_quest(client, gm))["occurrence"]["id"]
    steps.append((gm, "quest_offered", "quest_occurrence", player.id))
    await post(client, player, f"/quests/{occurrence_id}/accept")
    steps.append((player, "quest_accepted", "quest_occurrence", gm.id))
    await client.patch(f"/api/quests/{occurrence_id}", headers=auth(gm), json={"gold": 5})
    steps.append((gm, "quest_revision_proposed", "quest_occurrence", player.id))
    await post(client, player, f"/quests/{occurrence_id}/decline")
    steps.append((player, "quest_revision_declined", "quest_occurrence", gm.id))
    await client.patch(f"/api/quests/{occurrence_id}", headers=auth(gm), json={"gold": 6})
    steps.append((gm, "quest_revision_proposed", "quest_occurrence", player.id))
    await post(client, player, f"/quests/{occurrence_id}/accept")
    steps.append((player, "quest_revision_accepted", "quest_occurrence", gm.id))
    await post(client, gm, f"/quests/{occurrence_id}/cancel")
    steps.append((gm, "quest_cancelled", "quest_occurrence", player.id))
    template_id = (await create_quest(client, gm, recurrence="daily"))["template"]["id"]
    steps.append((gm, "quest_offered", "quest_template", player.id))
    await post(client, player, f"/quest-templates/{template_id}/decline")
    steps.append((player, "quest_declined", "quest_template", gm.id))

    events = list(await session.scalars(select(JournalEvent).order_by(JournalEvent.id)))
    notes = list(await session.scalars(select(Notification).order_by(Notification.id)))
    assert [(e.user_id, e.type, e.entity_type) for e in events] == [
        (s[0].id, s[1], s[2]) for s in steps
    ]
    assert [(n.recipient_id, n.type, n.entity_type) for n in notes] == [
        (s[3], s[1], s[2]) for s in steps
    ]
    for event in events:
        assert event.partnership_id == partnership.id
        assert event.visibility.value == "shared"
        check_payload(event.payload)
        assert gm.display_name not in str(event.payload)
        assert player.display_name not in str(event.payload)
    for note in notes:
        assert note.category == NotificationCategory.QUESTS
        # Dispatched right after each commit; these users never allowed bot messages.
        assert note.status == NotificationStatus.SKIPPED
        check_payload(note.payload)
    assert notes[0].deep_link == f"q_{occurrence_id}"
    assert notes[-1].deep_link == f"qt_{template_id}" and notes[-1].entity_id == template_id
    assert events[0].payload["title"] == "Morning run" and events[0].payload["xp"] == 50


async def test_payload_guard_rejects_names(session: AsyncSession) -> None:
    user = await factories.create_user(session)
    with pytest.raises(PayloadNameError):
        record_event(
            session,
            user_id=user.id,
            type="x",
            partnership_id=None,
            entity_type=None,
            entity_id=None,
            payload={"display_name": "Ann"},
        )
    with pytest.raises(PayloadNameError):
        enqueue(
            session,
            recipient_id=user.id,
            type="x",
            category=NotificationCategory.QUESTS,
            entity_type=None,
            entity_id=None,
            payload={"nested": [{"Nickname": "A"}]},
        )
    check_payload({"title": "ok", "items": [1, {"gold": 2}]})


async def _seed_pair(factory: async_sessionmaker[AsyncSession]) -> tuple[int, int]:
    async with factory() as s:
        gm = await factories.create_user(s, onboarded_at=clock.now())
        player = await factories.create_user(s, onboarded_at=clock.now())
        await factories.create_partnership(s, gm, player)
        await s.commit()
        return gm.id, player.id


async def _offer(factory: async_sessionmaker[AsyncSession], gm_id: int) -> int:
    async with factory() as s:
        gm = await s.get(User, gm_id)
        assert gm is not None
        created = await service.create(
            s,
            gm,
            get_settings(),
            QuestCreate(title="Run", attribute=Attribute.PHYSICAL, gold=10),
        )
        assert created.occurrence is not None
        return created.occurrence.id


async def test_rolled_back_transition_leaves_no_journal_or_notification(
    independent_sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    gm_id, player_id = await _seed_pair(independent_sessions)

    async with independent_sessions() as s:
        gm = await s.get(User, gm_id)
        assert gm is not None

        async def boom() -> None:
            raise RuntimeError("commit failed")

        monkeypatch.setattr(s, "commit", boom)
        with pytest.raises(RuntimeError):
            await service.create(
                s, gm, get_settings(), QuestCreate(title="Run", attribute="physical", gold=1)
            )
        await s.rollback()
    async with independent_sessions() as s:
        assert await counts(s) == (0, 0)
        assert await s.scalar(select(func.count()).select_from(QuestTemplate)) == 0

    occurrence_id = await _offer(independent_sessions, gm_id)
    async with independent_sessions() as s:
        player = await s.get(User, player_id)
        assert player is not None

        async def boom2() -> None:
            raise RuntimeError("commit failed")

        monkeypatch.setattr(s, "commit", boom2)
        with pytest.raises(RuntimeError):
            await service.accept(s, player, occurrence_id=occurrence_id)
        await s.rollback()
    async with independent_sessions() as s:
        assert await counts(s) == (1, 1)  # only the offer's
        occurrence = await s.get(QuestOccurrence, occurrence_id)
        assert occurrence is not None and occurrence.status == QuestOccurrenceStatus.OFFERED


async def test_concurrent_accepts_succeed_once(
    independent_sessions: async_sessionmaker[AsyncSession],
) -> None:
    gm_id, player_id = await _seed_pair(independent_sessions)
    occurrence_id = await _offer(independent_sessions, gm_id)

    async def accept() -> None:
        async with independent_sessions() as s:
            player = await s.get(User, player_id)
            assert player is not None
            await service.accept(s, player, occurrence_id=occurrence_id)

    results = await asyncio.gather(*(accept() for _ in range(5)), return_exceptions=True)
    assert sum(r is None for r in results) == 1
    assert all(isinstance(r, service.QuestStateError) for r in results if r is not None)
    async with independent_sessions() as s:
        assert await counts(s) == (2, 2)
        occurrence = await s.get(QuestOccurrence, occurrence_id)
        assert occurrence is not None and occurrence.status == QuestOccurrenceStatus.ACTIVE


async def test_concurrent_accept_and_cancel_serialize(
    independent_sessions: async_sessionmaker[AsyncSession],
) -> None:
    gm_id, player_id = await _seed_pair(independent_sessions)
    occurrence_id = await _offer(independent_sessions, gm_id)

    async def act(user_id: int, action: str) -> str:
        async with independent_sessions() as s:
            user = await s.get(User, user_id)
            assert user is not None
            if action == "accept":
                await service.accept(s, user, occurrence_id=occurrence_id)
            else:
                await service.cancel(s, user, occurrence_id=occurrence_id)
            return action

    results = await asyncio.gather(
        act(player_id, "accept"), act(gm_id, "cancel"), return_exceptions=True
    )
    async with independent_sessions() as s:
        occurrence = await s.get(QuestOccurrence, occurrence_id)
        assert occurrence is not None
        journal, notes = await counts(s)
    # Either order is valid: accept-then-cancel both succeed; cancel-then-accept refuses accept.
    if results[0] == "accept":
        assert results[1] == "cancel"
        assert occurrence.status == QuestOccurrenceStatus.CANCELLED
        assert (journal, notes) == (3, 3)
    else:
        assert isinstance(results[0], service.QuestStateError)
        assert occurrence.status == QuestOccurrenceStatus.CANCELLED
        assert (journal, notes) == (2, 2)


async def test_concurrent_revision_proposals_keep_one_pending(
    independent_sessions: async_sessionmaker[AsyncSession],
) -> None:
    gm_id, player_id = await _seed_pair(independent_sessions)
    occurrence_id = await _offer(independent_sessions, gm_id)
    async with independent_sessions() as s:
        player = await s.get(User, player_id)
        assert player is not None
        await service.accept(s, player, occurrence_id=occurrence_id)

    async def propose(gold: int) -> None:
        from app.modules.quests.schemas import QuestUpdate

        async with independent_sessions() as s:
            gm = await s.get(User, gm_id)
            assert gm is not None
            await service.update(
                s, gm, get_settings(), QuestUpdate(gold=gold), occurrence_id=occurrence_id
            )

    results = await asyncio.gather(*(propose(g) for g in (11, 12, 13, 14)), return_exceptions=True)
    assert results == [None] * 4
    async with independent_sessions() as s:
        pending = await s.scalar(
            select(func.count())
            .select_from(QuestRevision)
            .where(QuestRevision.status == QuestRevisionStatus.PENDING)
        )
        versions = await s.scalar(select(func.max(QuestRevision.version)))
    assert pending == 1 and versions == 5


# --- partnership end / account deletion ------------------------------------------------------


async def test_ended_partnership_quests_are_read_only_history(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, partnership = await pair(session)
    occurrence_id = (await create_quest(client, gm))["occurrence"]["id"]
    response = await client.post(
        "/api/partnership/leave", headers=auth(player), json={"confirm_text": "LEAVE"}
    )
    assert response.status_code == 204
    detail = await client.get(f"/api/quests/{occurrence_id}", headers=auth(gm))
    assert detail.status_code == 200 and detail.json()["status"] == "cancelled"
    for user, path in [
        (player, f"/quests/{occurrence_id}/accept"),
        (player, f"/quests/{occurrence_id}/decline"),
        (gm, f"/quests/{occurrence_id}/cancel"),
    ]:
        assert (await post(client, user, path)).status_code == 409
    patch = await client.patch(f"/api/quests/{occurrence_id}", headers=auth(gm), json={"gold": 1})
    assert patch.status_code == 409
    assert (await client.get("/api/quests", headers=auth(gm))).json() == []
    assert partnership.id


async def test_account_deletion_scrubs_revision_decline_reasons(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    template_id = (await create_quest(client, gm, recurrence="daily"))["template"]["id"]
    await post(client, player, f"/quest-templates/{template_id}/decline", {"reason": "Private"})
    response = await client.request(
        "DELETE", "/api/account", headers=auth(player), json={"confirm_text": "DELETE"}
    )
    assert response.status_code == 204, response.text
    revision = await session.scalar(
        select(QuestRevision)
        .where(QuestRevision.template_id == template_id)
        .execution_options(populate_existing=True)
    )
    assert revision is not None and revision.decline_reason is None


async def test_schema_allows_one_pending_revision_per_template(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, _, _ = await pair(session)
    template_id = (await create_quest(client, gm, recurrence="daily"))["template"]["id"]
    with pytest.raises(IntegrityError, match="ux_quest_revision_one_pending"):
        async with session.begin_nested():
            session.add(
                QuestRevision(
                    template_id=template_id,
                    version=2,
                    terms={},
                    status=QuestRevisionStatus.PENDING,
                    proposed_by=gm.id,
                )
            )
            await session.flush()


# --- closed quests and pending revisions -------------------------------------------------------


async def _revision(session: AsyncSession, template_id: int, version: int) -> QuestRevision:
    revision = await session.scalar(
        select(QuestRevision)
        .where(QuestRevision.template_id == template_id, QuestRevision.version == version)
        .execution_options(populate_existing=True)
    )
    assert revision is not None
    return revision


async def _leave_and_repair(
    client: httpx.AsyncClient, session: AsyncSession, player: User, partnership: Partnership
) -> None:
    """End the partnership, then reactivate the same row the way re-pairing does."""
    response = await client.post(
        "/api/partnership/leave", headers=auth(player), json={"confirm_text": "LEAVE"}
    )
    assert response.status_code == 204, response.text
    await session.refresh(partnership)
    partnership.status = PartnershipStatus.ACTIVE
    partnership.ended_at = None
    partnership.ended_by = None
    await session.flush()


async def _accepted_once_with_proposal(
    client: httpx.AsyncClient, gm: User, player: User
) -> tuple[int, int]:
    """(occurrence id, template id) of an accepted one-time quest with gold 77 proposed."""
    occurrence_id = (await create_quest(client, gm))["occurrence"]["id"]
    assert (await post(client, player, f"/quests/{occurrence_id}/accept")).status_code == 200
    patch = await client.patch(f"/api/quests/{occurrence_id}", headers=auth(gm), json={"gold": 77})
    assert patch.status_code == 200 and patch.json()["has_pending_revision"] is True
    return occurrence_id, patch.json()["template_id"]


async def test_pending_revision_on_a_closed_quest_cannot_be_decided_after_repair(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, partnership = await pair(session)
    occurrence_id, template_id = await _accepted_once_with_proposal(client, gm, player)
    await _leave_and_repair(client, session, player, partnership)
    before = await counts(session)

    for path in (
        f"/quests/{occurrence_id}/accept",
        f"/quests/{occurrence_id}/decline",
        f"/quest-templates/{template_id}/accept",
        f"/quest-templates/{template_id}/decline",
    ):
        assert (await post(client, player, path)).status_code == 409, path

    template = await session.get(QuestTemplate, template_id, populate_existing=True)
    assert template is not None
    assert template.status == QuestTemplateStatus.CANCELLED and template.gold == 50
    assert await counts(session) == before
    detail = (await client.get(f"/api/quests/{occurrence_id}", headers=auth(gm))).json()
    assert detail["status"] == "cancelled" and detail["terms"]["gold"] == 50
    assert detail["template"]["terms"]["gold"] == 50
    assert detail["has_pending_revision"] is False
    assert detail["template"]["pending_revision"] is None


async def test_stale_pending_revision_on_a_closed_template_is_refused_and_hidden(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """Even if a pending revision survives on a closed template (rows from before the fix, or a
    later close path that forgets to supersede), accept / decline give 409 and GET hides it."""
    gm, player, partnership = await pair(session)
    occurrence_id, template_id = await _accepted_once_with_proposal(client, gm, player)
    await _leave_and_repair(client, session, player, partnership)
    revision = await _revision(session, template_id, 2)
    revision.status = QuestRevisionStatus.PENDING
    revision.decided_at = None
    await session.flush()
    before = await counts(session)

    assert (await post(client, player, f"/quests/{occurrence_id}/accept")).status_code == 409
    decline = await post(client, player, f"/quests/{occurrence_id}/decline", {"reason": "No"})
    assert decline.status_code == 409
    template = await session.get(QuestTemplate, template_id, populate_existing=True)
    assert template is not None and template.gold == 50
    revision = await _revision(session, template_id, 2)
    assert revision.status == QuestRevisionStatus.PENDING and revision.decline_reason is None
    assert await counts(session) == before

    detail = (await client.get(f"/api/quests/{occurrence_id}", headers=auth(gm))).json()
    assert detail["has_pending_revision"] is False
    assert detail["template"]["pending_revision"] is None
    template_detail = await client.get(f"/api/quest-templates/{template_id}", headers=auth(gm))
    assert template_detail.json()["pending_revision"] is None
    listed = await client.get("/api/quest-templates", headers=auth(gm))
    assert all(t["pending_revision"] is None for t in listed.json())


async def test_decline_of_a_revision_on_a_finished_once_quest_is_409(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """A one-time quest needs its occurrence still active to decide a revision."""
    gm, player, _ = await pair(session)
    occurrence_id, template_id = await _accepted_once_with_proposal(client, gm, player)
    occurrence = await session.get(QuestOccurrence, occurrence_id)
    assert occurrence is not None
    occurrence.status = QuestOccurrenceStatus.IN_REVIEW
    await session.flush()
    for action in ("accept", "decline"):
        assert (await post(client, player, f"/quests/{occurrence_id}/{action}")).status_code == 409
    assert (await _revision(session, template_id, 2)).status == QuestRevisionStatus.PENDING


async def test_end_partnership_supersedes_pending_revisions(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    active_id = (await create_quest(client, gm, recurrence="daily"))["template"]["id"]
    await post(client, player, f"/quest-templates/{active_id}/accept")
    await client.patch(f"/api/quest-templates/{active_id}", headers=auth(gm), json={"gold": 9})
    offered_id = (await create_quest(client, gm, recurrence="weekly"))["template"]["id"]
    response = await client.post(
        "/api/partnership/leave", headers=auth(gm), json={"confirm_text": "LEAVE"}
    )
    assert response.status_code == 204
    pending = await session.scalar(
        select(func.count())
        .select_from(QuestRevision)
        .where(
            QuestRevision.template_id.in_([active_id, offered_id]),
            QuestRevision.status == QuestRevisionStatus.PENDING,
        )
    )
    assert pending == 0
    superseded = await _revision(session, active_id, 2)
    assert superseded.status == QuestRevisionStatus.SUPERSEDED
    assert superseded.decided_at is not None
    assert (await _revision(session, active_id, 1)).status == QuestRevisionStatus.ACCEPTED
    offer = await _revision(session, offered_id, 1)
    assert offer.status == QuestRevisionStatus.SUPERSEDED


async def test_cancelling_a_template_supersedes_its_pending_revision(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    template_id = (await create_quest(client, gm, recurrence="daily"))["template"]["id"]
    await post(client, player, f"/quest-templates/{template_id}/accept")
    await client.patch(f"/api/quest-templates/{template_id}", headers=auth(gm), json={"gold": 9})
    response = await post(client, gm, f"/quest-templates/{template_id}/cancel")
    assert response.status_code == 200
    assert response.json()["pending_revision"] is None
    assert (await _revision(session, template_id, 2)).status == QuestRevisionStatus.SUPERSEDED
    accept = await post(client, player, f"/quest-templates/{template_id}/accept")
    assert accept.status_code == 409

    # A one-time quest: cancelling its occurrence cancels the template and its proposal too.
    occurrence_id, once_id = await _accepted_once_with_proposal(client, gm, player)
    assert (await post(client, player, f"/quests/{occurrence_id}/cancel")).status_code == 200
    assert (await _revision(session, once_id, 2)).status == QuestRevisionStatus.SUPERSEDED
    assert (await post(client, player, f"/quests/{occurrence_id}/decline")).status_code == 409


async def test_revision_decline_reason_is_exposed_but_not_in_payloads(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    offer_id = (await create_quest(client, gm, recurrence="daily"))["template"]["id"]
    declined_offer = await post(
        client, player, f"/quest-templates/{offer_id}/decline", {"reason": "Not now"}
    )
    assert declined_offer.json()["last_declined_revision"]["decline_reason"] == "Not now"
    as_gm = await client.get(f"/api/quest-templates/{offer_id}", headers=auth(gm))
    assert as_gm.json()["last_declined_revision"]["decline_reason"] == "Not now"

    template_id = (await create_quest(client, gm, recurrence="weekly"))["template"]["id"]
    await post(client, player, f"/quest-templates/{template_id}/accept")
    proposed = await client.patch(
        f"/api/quest-templates/{template_id}", headers=auth(gm), json={"title": "Swim"}
    )
    assert proposed.json()["pending_revision"]["decline_reason"] is None
    assert proposed.json()["last_declined_revision"] is None
    await post(client, player, f"/quest-templates/{template_id}/decline", {"reason": "Secret pool"})
    detail = (await client.get(f"/api/quest-templates/{template_id}", headers=auth(gm))).json()
    assert detail["last_declined_revision"]["version"] == 2
    assert detail["last_declined_revision"]["decline_reason"] == "Secret pool"
    listed = await client.get("/api/quest-templates", headers=auth(gm))
    by_id = {t["id"]: t for t in listed.json()}
    assert by_id[template_id]["last_declined_revision"]["decline_reason"] == "Secret pool"
    assert by_id[offer_id]["last_declined_revision"]["decline_reason"] == "Not now"

    # A newer accepted revision replaces the declined one.
    await client.patch(f"/api/quest-templates/{template_id}", headers=auth(gm), json={"gold": 5})
    accepted = await post(client, player, f"/quest-templates/{template_id}/accept")
    assert accepted.json()["last_declined_revision"] is None

    payloads = [*await session.scalars(select(JournalEvent.payload))]
    payloads += [*await session.scalars(select(Notification.payload))]
    assert payloads
    for payload in payloads:
        assert "Secret pool" not in str(payload) and "Not now" not in str(payload)


async def test_offer_past_its_deadline_cannot_be_accepted(
    client: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    gm, player, _ = await pair(session)
    deadline = clock.now() + timedelta(hours=1)
    created = await create_quest(client, gm, deadline_at=deadline.isoformat())
    occurrence_id = created["occurrence"]["id"]
    frozen_clock.advance(timedelta(hours=1))
    before = await counts(session)
    response = await post(client, player, f"/quests/{occurrence_id}/accept")
    assert response.status_code == 409
    assert "deadline" in response.text
    assert await counts(session) == before
    detail = (await client.get(f"/api/quests/{occurrence_id}", headers=auth(player))).json()
    assert detail["status"] == "offered" and detail["accepted_at"] is None
    # Declining an offer whose deadline passed is still allowed.
    assert (await post(client, player, f"/quests/{occurrence_id}/decline")).status_code == 200
