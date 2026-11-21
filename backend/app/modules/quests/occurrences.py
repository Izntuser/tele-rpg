"""Occurrence creation shared by the offer flow and the recurrence job.

``ensure_occurrence`` is idempotent: the unique ``(template_id, scheduled_date)`` constraint and
``ON CONFLICT DO NOTHING`` make a second call (or a concurrent one, or the scheduler after a
restart) return the existing row instead of creating another.

Dates are calendar dates in the assignee's timezone: today for one-time and daily quests, the
Monday of the ISO week for weekly ones. A recurring occurrence is due at the start of the next
local day (daily) or week (weekly); a one-time occurrence is due at the template's deadline.
"""

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.modules.common.enums import QuestOccurrenceStatus, QuestTemplateStatus, Recurrence
from app.modules.quests.models import QuestOccurrence, QuestRevision, QuestTemplate


class TemplateNotSchedulableError(Exception):
    """Occurrences are only created for an offered one-time template or an active template."""


def period_start(recurrence: Recurrence, local_day: date) -> date:
    """The ``scheduled_date`` for ``local_day``: the day itself, or its ISO week's Monday."""
    if recurrence == Recurrence.WEEKLY:
        return local_day - timedelta(days=local_day.weekday())
    return local_day


def recurring_due_at(recurrence: Recurrence, scheduled: date, tz: str) -> datetime | None:
    """Local midnight that ends the occurrence's day or week, in UTC (None for one-time)."""
    if recurrence == Recurrence.ONCE:
        return None
    days = 7 if recurrence == Recurrence.WEEKLY else 1
    end = datetime.combine(scheduled + timedelta(days=days), time(0), tzinfo=ZoneInfo(tz))
    return end.astimezone(ZoneInfo("UTC"))


async def current_terms(session: AsyncSession, template: QuestTemplate) -> dict[str, Any]:
    revision = (
        await session.get(QuestRevision, template.current_revision_id)
        if template.current_revision_id is not None
        else None
    )
    if revision is None:  # pragma: no cover - every template is created with revision 1
        raise TemplateNotSchedulableError
    return dict(revision.terms)


async def ensure_occurrence(
    session: AsyncSession,
    template: QuestTemplate,
    assignee_timezone: str,
    *,
    on: date | None = None,
) -> tuple[QuestOccurrence, bool]:
    """The template's occurrence for the period containing ``on`` (default: today in the
    assignee's timezone), created if missing. Returns ``(occurrence, created)``.

    An offered one-time template gets an ``offered`` occurrence; an active template gets an
    ``active`` one (its terms were already accepted) with ``accepted_at`` set. Terms are a
    snapshot of the template's current revision, never edited afterwards by later revisions.
    """
    if template.status == QuestTemplateStatus.OFFERED and template.recurrence == Recurrence.ONCE:
        status = QuestOccurrenceStatus.OFFERED
    elif template.status == QuestTemplateStatus.ACTIVE:
        status = QuestOccurrenceStatus.ACTIVE
    else:
        raise TemplateNotSchedulableError
    local_day = on if on is not None else clock.today_in(assignee_timezone)
    scheduled = period_start(template.recurrence, local_day)
    due_at = (
        template.deadline_at
        if template.recurrence == Recurrence.ONCE
        else recurring_due_at(template.recurrence, scheduled, assignee_timezone)
    )
    now = clock.now()
    inserted = await session.scalar(
        insert(QuestOccurrence)
        .values(
            template_id=template.id,
            assignee_id=template.assignee_id,
            status=status,
            scheduled_date=scheduled,
            due_at=due_at,
            terms_snapshot=await current_terms(session, template),
            accepted_at=now if status == QuestOccurrenceStatus.ACTIVE else None,
        )
        .on_conflict_do_nothing(
            index_elements=[QuestOccurrence.template_id, QuestOccurrence.scheduled_date]
        )
        .returning(QuestOccurrence.id)
    )
    occurrence_id = inserted
    if occurrence_id is None:
        occurrence_id = await session.scalar(
            select(QuestOccurrence.id).where(
                QuestOccurrence.template_id == template.id,
                QuestOccurrence.scheduled_date == scheduled,
            )
        )
    occurrence = await session.get(QuestOccurrence, occurrence_id, populate_existing=True)
    assert occurrence is not None
    return occurrence, inserted is not None
