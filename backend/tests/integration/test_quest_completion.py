"""Quest completion over HTTP: submit (comment, attachment, photo rule), confirm (one transaction:
occurrence, wallet + ledger, XP, attributes, journal incl. level-ups, notification),
request-redo, auto-confirm through the same function, the authorization matrix, payout guards,
and the economy read endpoints."""

from datetime import timedelta
from types import ModuleType
from typing import Any

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock, ratelimit
from app.core.config import get_settings
from app.modules.common.enums import (
    Attribute,
    FileKind,
    GoldTransactionType,
    NotificationCategory,
    PartnershipStatus,
    QuestOccurrenceStatus,
    QuestRevisionStatus,
    QuestTemplateStatus,
)
from app.modules.economy import service as economy
from app.modules.economy.models import GoldTransaction
from app.modules.journal.models import JournalEvent
from app.modules.notifications.models import Notification
from app.modules.partnerships.models import Partnership
from app.modules.progression.models import XpTransaction
from app.modules.quests import completion, service
from app.modules.quests.models import (
    QuestOccurrence,
    QuestRevision,
    QuestStreak,
    QuestSubmission,
    QuestTemplate,
)
from app.modules.quests.occurrences import ensure_occurrence
from app.modules.quests.schemas import QuestUpdate
from app.modules.users.models import Character, CharacterAttribute, User
from tests import factories
from tests.integration.completion_support import (
    active_quest,
    assert_ledger_invariants,
    auth,
    count,
    pair,
    photo,
    wallet_balance,
)


@pytest.fixture(autouse=True)
def _clean_limiters() -> None:
    ratelimit.reset_all()


async def post(
    client: httpx.AsyncClient, user: User, path: str, body: dict[str, Any] | None = None
) -> httpx.Response:
    return await client.post(f"/api{path}", headers=auth(user), json=body)


async def attribute_xp(session: AsyncSession, user: User, attribute: Attribute) -> int:
    xp = await session.scalar(
        select(CharacterAttribute.xp)
        .join(Character, Character.id == CharacterAttribute.character_id)
        .where(Character.user_id == user.id, CharacterAttribute.attribute == attribute)
        .execution_options(populate_existing=True)
    )
    assert xp is not None
    return xp


async def total_xp(session: AsyncSession, user: User) -> int:
    xp = await session.scalar(
        select(Character.total_xp)
        .where(Character.user_id == user.id)
        .execution_options(populate_existing=True)
    )
    assert xp is not None
    return xp


# --- submit ----------------------------------------------------------------------------------


async def test_submit_puts_the_quest_in_review_without_paying(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, partnership = await pair(session)
    occ = await active_quest(session, gm, player)

    response = await post(client, player, f"/quests/{occ}/submit", {"comment": " Done!  "})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "in_review"
    assert body["submitted_at"] is not None
    assert body["completion"] is None
    [submission] = body["submissions"]
    assert submission["comment"] == "Done!"
    assert submission["submitted_by"] == player.id
    assert submission["review_status"] == "pending"
    assert await wallet_balance(session, player, partnership) == 0
    assert await count(session, XpTransaction) == 0
    note = await session.scalar(select(Notification).where(Notification.type == "quest_submitted"))
    assert note is not None
    assert note.recipient_id == gm.id
    assert note.category == NotificationCategory.REVIEWS
    assert "Done!" not in str(note.payload)
    event = await session.scalar(select(JournalEvent).where(JournalEvent.type == "quest_submitted"))
    assert event is not None and event.user_id == player.id


async def test_submit_with_my_quest_photo(client: httpx.AsyncClient, session: AsyncSession) -> None:
    gm, player, _ = await pair(session)
    occ = await active_quest(session, gm, player, photo_required=True)
    file = await photo(session, player)

    response = await post(client, player, f"/quests/{occ}/submit", {"attachment_id": file.id})
    assert response.status_code == 200, response.text
    assert response.json()["submissions"][0]["attachment_id"] == file.id


async def test_photo_required_quest_without_attachment_is_422(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    occ = await active_quest(session, gm, player, photo_required=True)

    response = await post(client, player, f"/quests/{occ}/submit", {"comment": "no photo"})
    assert response.status_code == 422
    occurrence = await session.get(QuestOccurrence, occ, populate_existing=True)
    assert occurrence is not None and occurrence.status == QuestOccurrenceStatus.ACTIVE
    assert await count(session, QuestSubmission) == 0


@pytest.mark.parametrize("whose", ["companion", "missing", "avatar"])
async def test_attachment_must_be_my_quest_photo(
    client: httpx.AsyncClient, session: AsyncSession, whose: str
) -> None:
    gm, player, _ = await pair(session)
    occ = await active_quest(session, gm, player)
    if whose == "companion":
        attachment_id = (await photo(session, gm)).id
    elif whose == "avatar":
        attachment_id = (await photo(session, player, FileKind.AVATAR)).id
    else:
        attachment_id = 987_654_321

    response = await post(client, player, f"/quests/{occ}/submit", {"attachment_id": attachment_id})
    assert response.status_code == 422
    assert await count(session, QuestSubmission) == 0


async def test_submit_after_the_deadline_is_refused(
    client: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    gm, player, _ = await pair(session)
    deadline = clock.now() + timedelta(hours=2)
    occ = await active_quest(session, gm, player, deadline_at=deadline)
    frozen_clock.advance(timedelta(hours=3))

    response = await post(client, player, f"/quests/{occ}/submit")
    assert response.status_code == 409


async def test_a_submitted_quest_can_be_confirmed_after_its_deadline(
    client: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    gm, player, partnership = await pair(session)
    occ = await active_quest(session, gm, player, deadline_at=clock.now() + timedelta(hours=2))
    assert (await post(client, player, f"/quests/{occ}/submit")).status_code == 200
    frozen_clock.advance(timedelta(days=2))

    response = await post(client, gm, f"/quests/{occ}/confirm")
    assert response.status_code == 200, response.text
    assert await wallet_balance(session, player, partnership) == 40


# --- confirm ---------------------------------------------------------------------------------


async def test_confirm_completes_and_pays_in_one_transaction(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, partnership = await pair(session)
    occ = await active_quest(session, gm, player, gold=40, attribute="social")
    assert (await post(client, player, f"/quests/{occ}/submit")).status_code == 200

    response = await post(client, gm, f"/quests/{occ}/confirm", {"feedback": "Great job"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["completed_at"] is not None
    assert body["template_status"] == "completed"
    assert body["submissions"][0]["review_status"] == "approved"
    assert body["submissions"][0]["review_comment"] == "Great job"
    assert body["completion"] == {
        "gold": 40,
        "xp": 50,
        "attribute": "social",
        "attribute_xp": 50,
        "total_xp": 50,
        "level_before": 1,
        "level": 1,
        "attribute_level_before": 1,
        "attribute_level": 1,
        "balance": 40,
    }

    [tx] = (await session.scalars(select(GoldTransaction))).all()
    assert tx.idempotency_key == f"quest:{occ}"
    assert tx.type == GoldTransactionType.QUEST_REWARD
    assert (tx.user_id, tx.partnership_id, tx.amount) == (player.id, partnership.id, 40)
    assert tx.quest_occurrence_id == occ
    [xp] = (await session.scalars(select(XpTransaction))).all()
    assert (xp.user_id, xp.quest_occurrence_id, xp.xp, xp.attribute, xp.attribute_xp) == (
        player.id,
        occ,
        50,
        Attribute.SOCIAL,
        50,
    )
    assert await wallet_balance(session, player, partnership) == 40
    assert await wallet_balance(session, gm, partnership) == 0  # Gold is not taken from the GM
    assert await total_xp(session, player) == 50
    assert await attribute_xp(session, player, Attribute.SOCIAL) == 50
    assert await attribute_xp(session, player, Attribute.PHYSICAL) == 0
    assert await total_xp(session, gm) == 0

    completed = await session.scalar(
        select(JournalEvent).where(JournalEvent.type == "quest_completed")
    )
    assert completed is not None
    assert completed.user_id == player.id
    assert completed.payload["gold"] == 40 and completed.payload["xp"] == 50
    assert completed.payload["auto_confirmed"] is False
    assert "Great job" not in str(completed.payload)
    note = await session.scalar(select(Notification).where(Notification.type == "quest_confirmed"))
    assert note is not None
    assert note.recipient_id == player.id and note.category == NotificationCategory.REVIEWS
    assert await count(session, JournalEvent, JournalEvent.type == "level_up") == 0
    await assert_ledger_invariants(session)


async def test_level_up_writes_journal_events(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    occ = await active_quest(session, gm, player, difficulty="epic", attribute="creativity")
    await post(client, player, f"/quests/{occ}/submit")

    response = await post(client, gm, f"/quests/{occ}/confirm")
    assert response.status_code == 200, response.text
    completion_out = response.json()["completion"]
    assert completion_out["xp"] == 250
    assert (completion_out["level_before"], completion_out["level"]) == (1, 3)
    assert (completion_out["attribute_level_before"], completion_out["attribute_level"]) == (1, 3)

    level_up = await session.scalar(select(JournalEvent).where(JournalEvent.type == "level_up"))
    assert level_up is not None
    assert level_up.user_id == player.id
    assert level_up.payload == {"occurrence_id": occ, "previous_level": 1, "level": 3}
    attr_up = await session.scalar(
        select(JournalEvent).where(JournalEvent.type == "attribute_level_up")
    )
    assert attr_up is not None
    assert attr_up.payload["attribute"] == "creativity" and attr_up.payload["level"] == 3


async def test_client_supplied_amounts_are_ignored(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, partnership = await pair(session)
    occ = await active_quest(session, gm, player, gold=25, difficulty="easy")
    await post(client, player, f"/quests/{occ}/submit", {"gold": 999, "xp": 999})

    response = await post(client, gm, f"/quests/{occ}/confirm", {"gold": 999, "xp": 5000})
    assert response.status_code == 200
    assert await wallet_balance(session, player, partnership) == 25
    assert await total_xp(session, player) == 20


async def test_payout_uses_the_snapshot_not_the_live_template(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, partnership = await pair(session)
    occ = await active_quest(session, gm, player, gold=30)
    occurrence = await session.get(QuestOccurrence, occ)
    assert occurrence is not None
    await session.execute(
        update(QuestTemplate).where(QuestTemplate.id == occurrence.template_id).values(gold=1000)
    )
    await post(client, player, f"/quests/{occ}/submit")
    await post(client, gm, f"/quests/{occ}/confirm")
    assert await wallet_balance(session, player, partnership) == 30


async def test_confirm_twice_pays_once(client: httpx.AsyncClient, session: AsyncSession) -> None:
    gm, player, partnership = await pair(session)
    occ = await active_quest(session, gm, player)
    await post(client, player, f"/quests/{occ}/submit")
    assert (await post(client, gm, f"/quests/{occ}/confirm")).status_code == 200

    again = await post(client, gm, f"/quests/{occ}/confirm")
    assert again.status_code == 409
    assert await count(session, GoldTransaction) == 1
    assert await count(session, XpTransaction) == 1
    assert await wallet_balance(session, player, partnership) == 40


async def test_confirm_requires_in_review(client: httpx.AsyncClient, session: AsyncSession) -> None:
    gm, player, _ = await pair(session)
    occ = await active_quest(session, gm, player)
    assert (await post(client, gm, f"/quests/{occ}/confirm")).status_code == 409
    assert (
        await post(client, gm, f"/quests/{occ}/request-redo", {"reason": "again"})
    ).status_code == 409
    assert await count(session, GoldTransaction) == 0


async def test_submit_requires_active(client: httpx.AsyncClient, session: AsyncSession) -> None:
    gm, player, _ = await pair(session)
    created = await client.post(
        "/api/quests",
        headers=auth(gm),
        json={"title": "Offer", "attribute": "physical", "gold": 5},
    )
    offered = created.json()["occurrence"]["id"]
    occ = await active_quest(session, gm, player)
    assert (await post(client, player, f"/quests/{offered}/submit")).status_code == 409

    assert (await post(client, player, f"/quests/{occ}/submit")).status_code == 200
    assert (await post(client, player, f"/quests/{occ}/submit")).status_code == 409


# --- request redo ----------------------------------------------------------------------------


@pytest.mark.parametrize("body", [None, {}, {"reason": ""}, {"reason": "   \n "}, {"reason": None}])
async def test_redo_requires_a_reason(
    client: httpx.AsyncClient, session: AsyncSession, body: dict[str, Any] | None
) -> None:
    gm, player, _ = await pair(session)
    occ = await active_quest(session, gm, player)
    await post(client, player, f"/quests/{occ}/submit")

    response = await post(client, gm, f"/quests/{occ}/request-redo", body)
    assert response.status_code == 422
    occurrence = await session.get(QuestOccurrence, occ, populate_existing=True)
    assert occurrence is not None and occurrence.status == QuestOccurrenceStatus.IN_REVIEW


async def test_redo_returns_the_quest_to_active_then_it_can_complete(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, partnership = await pair(session)
    occ = await active_quest(session, gm, player)
    await post(client, player, f"/quests/{occ}/submit", {"comment": "first"})

    response = await post(client, gm, f"/quests/{occ}/request-redo", {"reason": "Photo is blurry"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "active"
    assert body["completion"] is None
    [first] = body["submissions"]
    assert first["review_status"] == "redo"
    assert first["review_comment"] == "Photo is blurry"
    assert first["reviewed_at"] is not None
    assert await count(session, GoldTransaction) == 0
    note = await session.scalar(
        select(Notification).where(Notification.type == "quest_redo_requested")
    )
    assert note is not None and note.recipient_id == player.id
    assert "blurry" not in str(note.payload)

    assert (
        await post(client, player, f"/quests/{occ}/submit", {"comment": "2nd"})
    ).status_code == 200
    confirmed = await post(client, gm, f"/quests/{occ}/confirm")
    assert confirmed.status_code == 200
    statuses = [s["review_status"] for s in confirmed.json()["submissions"]]
    assert statuses == ["redo", "approved"]
    assert await wallet_balance(session, player, partnership) == 40


# --- authorization ---------------------------------------------------------------------------


async def test_only_the_assignee_submits_and_only_the_creator_reviews(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    outsider = await factories.create_user(session, onboarded_at=clock.now())
    occ = await active_quest(session, gm, player)

    assert (await post(client, gm, f"/quests/{occ}/submit")).status_code == 403
    assert (await post(client, outsider, f"/quests/{occ}/submit")).status_code == 404
    assert (await post(client, player, f"/quests/{occ}/submit")).status_code == 200

    # The assignee can never confirm (or reject) their own quest.
    assert (await post(client, player, f"/quests/{occ}/confirm")).status_code == 403
    redo = {"reason": "nope"}
    assert (await post(client, player, f"/quests/{occ}/request-redo", redo)).status_code == 403
    assert (await post(client, outsider, f"/quests/{occ}/confirm")).status_code == 404
    assert (await post(client, outsider, f"/quests/{occ}/request-redo", redo)).status_code == 404
    assert (await post(client, gm, "/quests/999999999/confirm")).status_code == 404
    assert await count(session, GoldTransaction) == 0
    assert (await post(client, gm, f"/quests/{occ}/confirm")).status_code == 200


async def test_completion_routes_require_auth(client: httpx.AsyncClient) -> None:
    for action in ("submit", "confirm", "request-redo"):
        response = await client.post(f"/api/quests/1/{action}", json={"reason": "x"})
        assert response.status_code == 401


# --- auto-confirm ----------------------------------------------------------------------------


async def test_auto_confirm_completes_on_submit(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, partnership = await pair(session)
    occ = await active_quest(session, gm, player, confirmation="auto", gold=15)

    response = await post(client, player, f"/quests/{occ}/submit")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["completion"]["gold"] == 15
    assert body["submissions"][0]["review_status"] == "approved"
    assert await wallet_balance(session, player, partnership) == 15
    note = await session.scalar(select(Notification).where(Notification.type == "quest_completed"))
    assert note is not None and note.recipient_id == gm.id
    assert await count(session, Notification, Notification.type == "quest_submitted") == 0
    event = await session.scalar(select(JournalEvent).where(JournalEvent.type == "quest_completed"))
    assert event is not None and event.payload["auto_confirmed"] is True
    assert (await post(client, gm, f"/quests/{occ}/confirm")).status_code == 409


async def test_both_paths_call_complete_occurrence(
    client: httpx.AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[int, int]] = []
    real = completion.complete_occurrence

    async def spy(session: AsyncSession, **kwargs: Any) -> Any:
        calls.append((kwargs["occurrence"].id, kwargs["actor_id"]))
        return await real(session, **kwargs)

    monkeypatch.setattr(completion, "complete_occurrence", spy)
    gm, player, _ = await pair(session)
    manual = await active_quest(session, gm, player)
    auto = await active_quest(session, gm, player, confirmation="auto")

    await post(client, player, f"/quests/{manual}/submit")
    assert calls == []
    assert (await post(client, gm, f"/quests/{manual}/confirm")).status_code == 200
    assert (await post(client, player, f"/quests/{auto}/submit")).status_code == 200
    assert calls == [(manual, gm.id), (auto, player.id)]


# --- payout guards ---------------------------------------------------------------------------


async def test_no_payout_on_an_ended_partnership(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, partnership = await pair(session)
    occ = await active_quest(session, gm, player)
    await post(client, player, f"/quests/{occ}/submit")
    await session.execute(
        update(Partnership)
        .where(Partnership.id == partnership.id)
        .values(status=PartnershipStatus.ENDED, ended_at=clock.now())
    )

    assert (await post(client, gm, f"/quests/{occ}/confirm")).status_code == 409
    assert await count(session, GoldTransaction) == 0
    assert await count(session, XpTransaction) == 0


async def test_leaving_cancels_in_review_quests_so_nothing_pays(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    occ = await active_quest(session, gm, player)
    await post(client, player, f"/quests/{occ}/submit")
    leave = await client.post(
        "/api/partnership/leave", headers=auth(player), json={"confirm_text": "LEAVE"}
    )
    assert leave.status_code in (200, 204), leave.text

    assert (await post(client, gm, f"/quests/{occ}/confirm")).status_code == 409
    occurrence = await session.get(QuestOccurrence, occ, populate_existing=True)
    assert occurrence is not None and occurrence.status == QuestOccurrenceStatus.CANCELLED
    assert await count(session, GoldTransaction) == 0


async def test_no_payout_to_a_deleted_member(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    occ = await active_quest(session, gm, player)
    await post(client, player, f"/quests/{occ}/submit")
    # Deletion always ends the partnership; this guards the payout even if a row is stale.
    await session.execute(update(User).where(User.id == player.id).values(deleted_at=clock.now()))

    assert (await post(client, gm, f"/quests/{occ}/confirm")).status_code == 409
    assert await count(session, GoldTransaction) == 0


async def test_in_review_occurrence_of_a_cancelled_recurring_quest_still_pays(
    client: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    gm, player, partnership = await pair(session)
    occ = await active_quest(session, gm, player, recurrence="daily")
    await post(client, player, f"/quests/{occ}/submit")
    occurrence = await session.get(QuestOccurrence, occ)
    assert occurrence is not None
    cancel = await post(client, gm, f"/quest-templates/{occurrence.template_id}/cancel")
    assert cancel.status_code == 200

    assert (await post(client, gm, f"/quests/{occ}/confirm")).status_code == 200
    assert await wallet_balance(session, player, partnership) == 40
    template = await session.get(QuestTemplate, occurrence.template_id, populate_existing=True)
    assert template is not None and template.status == QuestTemplateStatus.CANCELLED


async def test_submit_supersedes_a_pending_revision_of_a_one_time_quest(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, partnership = await pair(session)
    occ = await active_quest(session, gm, player, gold=40)
    await service.update(session, gm, get_settings(), QuestUpdate(gold=5), occurrence_id=occ)

    response = await post(client, player, f"/quests/{occ}/submit")
    assert response.status_code == 200
    assert response.json()["has_pending_revision"] is False
    occurrence = await session.get(QuestOccurrence, occ)
    assert occurrence is not None
    statuses = (
        await session.scalars(
            select(QuestRevision.status)
            .where(QuestRevision.template_id == occurrence.template_id)
            .order_by(QuestRevision.version)
        )
    ).all()
    assert statuses == [QuestRevisionStatus.ACCEPTED, QuestRevisionStatus.SUPERSEDED]
    await post(client, gm, f"/quests/{occ}/confirm")
    assert await wallet_balance(session, player, partnership) == 40


async def test_daily_streak_counts_consecutive_completions(
    client: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    gm, player, _ = await pair(session)
    first = await active_quest(session, gm, player, recurrence="daily", confirmation="auto")
    occurrence = await session.get(QuestOccurrence, first)
    assert occurrence is not None
    template_id = occurrence.template_id
    assert (await post(client, player, f"/quests/{first}/submit")).status_code == 200

    async def next_day() -> int:
        frozen_clock.advance(timedelta(days=1))
        template = await session.get(QuestTemplate, template_id, populate_existing=True)
        assert template is not None
        occ, _ = await ensure_occurrence(session, template, "UTC")
        await session.commit()
        return occ.id

    second = await next_day()
    assert (await post(client, player, f"/quests/{second}/submit")).status_code == 200
    streak = await session.get(QuestStreak, template_id, populate_existing=True)
    assert streak is not None and (streak.current, streak.best) == (2, 2)

    await next_day()  # skipped day
    fourth = await next_day()
    assert (await post(client, player, f"/quests/{fourth}/submit")).status_code == 200
    streak = await session.get(QuestStreak, template_id, populate_existing=True)
    assert streak is not None and (streak.current, streak.best) == (1, 2)
    await assert_ledger_invariants(session)


async def test_submission_review_rows_never_leak_into_payloads(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await pair(session)
    occ = await active_quest(session, gm, player)
    await post(client, player, f"/quests/{occ}/submit", {"comment": "secret-comment"})
    await post(client, gm, f"/quests/{occ}/request-redo", {"reason": "secret-reason"})
    await post(client, player, f"/quests/{occ}/submit")
    await post(client, gm, f"/quests/{occ}/confirm", {"feedback": "secret-feedback"})
    payloads = [str(p) for p in (await session.scalars(select(JournalEvent.payload))).all()]
    payloads += [str(p) for p in (await session.scalars(select(Notification.payload))).all()]
    assert payloads
    assert not any("secret" in p for p in payloads)


# --- economy endpoints -----------------------------------------------------------------------


async def test_balance_shows_the_active_wallet_and_frozen_ones(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    me = await factories.create_user(session, onboarded_at=clock.now())
    old_partner = await factories.create_user(session)
    new_partner = await factories.create_user(session)
    ended = await factories.create_partnership(
        session, me, old_partner, status=PartnershipStatus.ENDED
    )
    active = await factories.create_partnership(session, me, new_partner)
    await factories.create_wallet(session, me, ended, balance=70)
    await factories.create_wallet(session, me, active, balance=20)
    await factories.create_wallet(session, new_partner, active, balance=999)

    response = await client.get("/api/economy/balance", headers=auth(me))
    assert response.status_code == 200
    body = response.json()
    assert body["active"]["partnership_id"] == active.id
    assert body["active"]["balance"] == 20 and body["active"]["frozen"] is False
    [frozen] = body["frozen"]
    assert frozen["partnership_id"] == ended.id and frozen["balance"] == 70
    assert frozen["frozen"] is True and frozen["ended_at"] is not None


async def test_balance_without_any_wallet(client: httpx.AsyncClient, session: AsyncSession) -> None:
    me = await factories.create_user(session)
    response = await client.get("/api/economy/balance", headers=auth(me))
    assert response.json() == {"active": None, "frozen": []}


async def test_transactions_are_mine_only_and_cursor_paginated(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, partnership = await pair(session)
    for i in range(5):
        await economy.post(
            session,
            user_id=player.id,
            partnership_id=partnership.id,
            type=GoldTransactionType.ADJUSTMENT,
            amount=i + 1,
            key=f"test:player:{i}",
        )
    await economy.post(
        session,
        user_id=gm.id,
        partnership_id=partnership.id,
        type=GoldTransactionType.ADJUSTMENT,
        amount=3,
        key="test:gm",
    )

    seen: list[int] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, Any] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        response = await client.get(
            "/api/economy/transactions", headers=auth(player), params=params
        )
        assert response.status_code == 200, response.text
        page = response.json()
        pages += 1
        assert len(page["items"]) <= 2
        for item in page["items"]:
            assert "idempotency_key" not in item
            assert item["type"] == "adjustment"
        seen += [item["amount"] for item in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == [5, 4, 3, 2, 1]  # newest first, no gm row
    assert pages == 3

    gm_page = (await client.get("/api/economy/transactions", headers=auth(gm))).json()
    assert [i["amount"] for i in gm_page["items"]] == [3]
    assert gm_page["next_cursor"] is None


@pytest.mark.parametrize("cursor", ["garbage", "dHg6LTE", "Zm9vOjE", "dHg6MA", "dHg6KzU"])
async def test_transactions_reject_a_bad_cursor(
    client: httpx.AsyncClient, session: AsyncSession, cursor: str
) -> None:
    me = await factories.create_user(session)
    response = await client.get(
        "/api/economy/transactions", headers=auth(me), params={"cursor": cursor}
    )
    assert response.status_code == 422


async def test_economy_routes_require_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/economy/balance")).status_code == 401
    assert (await client.get("/api/economy/transactions")).status_code == 401


async def test_debit_cannot_make_a_balance_negative(session: AsyncSession) -> None:
    _, player, partnership = await pair(session)
    await economy.post(
        session,
        user_id=player.id,
        partnership_id=partnership.id,
        type=GoldTransactionType.ADJUSTMENT,
        amount=10,
        key="test:credit",
    )
    with pytest.raises(economy.InsufficientGoldError):
        await economy.post(
            session,
            user_id=player.id,
            partnership_id=partnership.id,
            type=GoldTransactionType.ADJUSTMENT,
            amount=-11,
            key="test:debit",
        )
    assert await wallet_balance(session, player, partnership) == 10
    assert (
        await count(session, GoldTransaction, GoldTransaction.idempotency_key == "test:debit") == 0
    )
    with pytest.raises(economy.DuplicateLedgerEntryError):
        await economy.post(
            session,
            user_id=player.id,
            partnership_id=partnership.id,
            type=GoldTransactionType.ADJUSTMENT,
            amount=5,
            key="test:credit",
        )


def test_ledger_keys_are_namespaced() -> None:
    assert economy.quest_reward_key(7) == "quest:7"
    assert economy.refund_key(3) == "refund:3"
    assert economy.purchase_key(5, "abc") == "purchase:5:abc"
    assert economy.purchase_key(5, "abc") != economy.purchase_key(6, "abc")
    longest = economy.purchase_key(2**63 - 1, "k" * economy.MAX_CLIENT_KEY_LEN)
    assert len(longest) <= 255
    with pytest.raises(ValueError):
        economy.purchase_key(5, "k" * (economy.MAX_CLIENT_KEY_LEN + 1))
    with pytest.raises(ValueError):
        economy.purchase_key(5, "")


def test_cursor_round_trip() -> None:
    assert economy.decode_cursor(economy.encode_cursor(42)).before_id == 42
