"""Scheduler jobs for notifications (ARCHITECTURE §3, DECISIONS 20).

- ``dispatch_outbox`` (every 30 s): the outbox sweep, a fallback for the API's post-commit send
  and the sender of deferred (quiet hours) and retried rows.
- ``deadline_reminders`` (every 5 min): one ``deadline_reminder`` per active occurrence whose
  deadline is less than ``REMINDER_LEAD`` away, to its player.
- ``daily_summary`` (every 5 min): one ``daily_summary`` per user and local day, from 09:00
  local (until ``SUMMARY_UNTIL``, so a runner that was down at 09:00 still catches up), only
  when there is something to report and the user has not turned it off.

Reminders and summaries are created only outside the recipient's quiet hours and are
deduplicated per day twice: a ``NOT EXISTS`` / fixed ``send_after`` here, and the
``ux_notification_dedupe`` unique index (``ON CONFLICT DO NOTHING``) as the backstop against a
concurrent run. Each job is a pure function of DB state, so a restart catches up.
"""

import logging
from datetime import UTC, datetime, time, timedelta
from typing import Any

from sqlalchemy import exists, func, literal_column, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.dispatcher import get_bot
from app.core import clock
from app.modules.common.enums import (
    NotificationCategory,
    NotificationStatus,
    QuestOccurrenceStatus,
    QuestTemplateStatus,
)
from app.modules.journal.service import check_payload
from app.modules.notifications import dispatcher
from app.modules.notifications.models import Notification
from app.modules.notifications.service import is_quiet, prefs_of, quest_deep_link, zone_of
from app.modules.quests.models import QuestOccurrence, QuestTemplate
from app.modules.users.models import User

log = logging.getLogger(__name__)

REMINDER_TYPE = "deadline_reminder"
SUMMARY_TYPE = "daily_summary"
REMINDER_LEAD = timedelta(hours=3)
SUMMARY_TIME = time(9, 0)
SUMMARY_UNTIL = time(12, 0)

_DEDUPE_COLUMNS = (
    "recipient_id",
    "type",
    "entity_id",
    text("((send_after AT TIME ZONE 'UTC')::date)"),
)
# A literal predicate: ON CONFLICT cannot infer a partial index from a bound parameter.
_DEDUPE_WHERE = text("category IN ('reminders', 'summary')")


async def _insert_deduped(session: AsyncSession, **values: Any) -> bool:
    check_payload(values["payload"])
    stmt: Any = (
        insert(Notification)
        .values(status=NotificationStatus.PENDING, **values)
        .on_conflict_do_nothing(index_elements=list(_DEDUPE_COLUMNS), index_where=_DEDUPE_WHERE)
        .returning(literal_column("1"))
    )
    return (await session.execute(stmt)).first() is not None


async def dispatch_outbox(session: AsyncSession) -> dispatcher.DispatchResult:
    return await dispatcher.dispatch(session, get_bot())


async def deadline_reminders(session: AsyncSession) -> int:
    now = clock.now()
    reminded = exists().where(
        Notification.type == REMINDER_TYPE,
        Notification.entity_type == "quest_occurrence",
        Notification.entity_id == QuestOccurrence.id,
    )
    rows = (
        await session.execute(
            select(QuestOccurrence, User)
            .join(User, User.id == QuestOccurrence.assignee_id)
            .where(
                QuestOccurrence.status == QuestOccurrenceStatus.ACTIVE,
                QuestOccurrence.due_at > now,
                QuestOccurrence.due_at <= now + REMINDER_LEAD,
                User.deleted_at.is_(None),
                ~reminded,
            )
            .order_by(QuestOccurrence.id)
        )
    ).all()
    created = 0
    for occurrence, user in rows:
        if is_quiet(now, user):
            continue  # a later run inside the lead window tries again
        terms = occurrence.terms_snapshot
        assert occurrence.due_at is not None
        if await _insert_deduped(
            session,
            recipient_id=user.id,
            type=REMINDER_TYPE,
            category=NotificationCategory.REMINDERS,
            entity_type="quest_occurrence",
            entity_id=occurrence.id,
            payload={
                "occurrence_id": occurrence.id,
                "template_id": occurrence.template_id,
                "title": terms.get("title", ""),
                "due_at": occurrence.due_at.astimezone(UTC).isoformat(),
            },
            deep_link=quest_deep_link(occurrence.id),
            send_after=now,
        ):
            created += 1
    await session.commit()
    if created:
        log.info("deadline_reminders created %s reminder(s)", created)
    return created


async def _summary_counts(session: AsyncSession, user_id: int) -> dict[str, int]:
    active = await session.scalar(
        select(func.count())
        .select_from(QuestOccurrence)
        .where(
            QuestOccurrence.assignee_id == user_id,
            QuestOccurrence.status == QuestOccurrenceStatus.ACTIVE,
        )
    )
    offers = await session.scalar(
        select(func.count())
        .select_from(QuestTemplate)
        .where(
            QuestTemplate.assignee_id == user_id,
            QuestTemplate.status == QuestTemplateStatus.OFFERED,
        )
    )
    reviews = await session.scalar(
        select(func.count())
        .select_from(QuestOccurrence)
        .join(QuestTemplate, QuestTemplate.id == QuestOccurrence.template_id)
        .where(
            QuestTemplate.creator_id == user_id,
            QuestOccurrence.status == QuestOccurrenceStatus.IN_REVIEW,
        )
    )
    return {"active": int(active or 0), "offers": int(offers or 0), "reviews": int(reviews or 0)}


def summary_send_at(now: datetime, timezone: str | None) -> datetime | None:
    """09:00 of the user's current local day (UTC) when ``now`` is inside the summary window,
    else None. Fixed per local day, so every run that day produces the same row."""
    zone = zone_of(timezone)
    local = now.astimezone(zone)
    if not (SUMMARY_TIME <= local.time().replace(tzinfo=None) < SUMMARY_UNTIL):
        return None
    return datetime.combine(local.date(), SUMMARY_TIME, tzinfo=zone).astimezone(UTC)


async def daily_summary(session: AsyncSession) -> int:
    now = clock.now()
    users = list(
        await session.scalars(
            select(User)
            .where(
                User.deleted_at.is_(None),
                User.tg_user_id > 0,
                User.onboarded_at.is_not(None),
            )
            .order_by(User.id)
        )
    )
    created = 0
    for user in users:
        prefs = prefs_of(user)
        send_at = summary_send_at(now, user.timezone)
        if send_at is None or not prefs.daily_summary or is_quiet(now, user, prefs):
            continue
        counts = await _summary_counts(session, user.id)
        if not any(counts.values()):
            continue
        if await _insert_deduped(
            session,
            recipient_id=user.id,
            type=SUMMARY_TYPE,
            category=NotificationCategory.SUMMARY,
            entity_type=None,
            entity_id=None,
            payload=counts,
            deep_link=None,
            send_after=send_at,
        ):
            created += 1
    await session.commit()
    if created:
        log.info("daily_summary created %s summary(ies)", created)
    return created
