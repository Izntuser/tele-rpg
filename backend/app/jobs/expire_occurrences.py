"""Move active occurrences past ``due_at`` to ``expired``; a missed daily quest breaks its streak
and both members get a ``quest_expired`` notification.

Only ``active`` rows are considered: an occurrence in review is waiting for the creator and is
never expired. Each occurrence is its own transaction (partnership ``FOR SHARE``, template,
occurrence, then the streak) and its state is re-checked under the lock, so a submit that wins
the race keeps its occurrence.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.modules.common.enums import NotificationCategory, QuestOccurrenceStatus, Recurrence
from app.modules.notifications.service import enqueue
from app.modules.partnerships.models import Partnership
from app.modules.quests import state, streaks
from app.modules.quests.models import QuestOccurrence, QuestTemplate

log = logging.getLogger(__name__)


def _notify_expired(
    session: AsyncSession, template: QuestTemplate, occurrence: QuestOccurrence
) -> None:
    """Both members learn that the deadline passed (in the expiry's own transaction)."""
    payload = {
        "occurrence_id": occurrence.id,
        "template_id": template.id,
        "title": occurrence.terms_snapshot.get("title", template.title),
        "recurrence": template.recurrence.value,
    }
    for recipient_id in dict.fromkeys((occurrence.assignee_id, template.creator_id)):
        enqueue(
            session,
            recipient_id=recipient_id,
            type="quest_expired",
            category=NotificationCategory.QUESTS,
            entity_type="quest_occurrence",
            entity_id=occurrence.id,
            payload=payload,
        )


async def _expire_one(session: AsyncSession, occurrence_id: int) -> bool:
    ids = (
        await session.execute(
            select(QuestTemplate.id, QuestTemplate.partnership_id)
            .join(QuestOccurrence, QuestOccurrence.template_id == QuestTemplate.id)
            .where(QuestOccurrence.id == occurrence_id)
        )
    ).one_or_none()
    if ids is None:  # pragma: no cover - occurrences are never deleted
        return False
    template_id, partnership_id = ids
    await session.scalar(
        select(Partnership.id).where(Partnership.id == partnership_id).with_for_update(read=True)
    )
    template = await session.scalar(
        select(QuestTemplate)
        .where(QuestTemplate.id == template_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    occurrence = await session.scalar(
        select(QuestOccurrence)
        .where(QuestOccurrence.id == occurrence_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert template is not None and occurrence is not None
    expired = False
    if (
        occurrence.status == QuestOccurrenceStatus.ACTIVE
        and occurrence.due_at is not None
        and occurrence.due_at <= clock.now()
    ):
        occurrence.status = state.next_occurrence_status(occurrence.status, "expire")
        if template.recurrence == Recurrence.DAILY:
            await streaks.break_streak(session, template.id, occurrence.scheduled_date)
        _notify_expired(session, template, occurrence)
        expired = True
    await session.commit()
    return expired


async def run(session: AsyncSession) -> int:
    """Expire what is overdue; returns how many occurrences were expired."""
    ids = list(
        await session.scalars(
            select(QuestOccurrence.id)
            .where(
                QuestOccurrence.status == QuestOccurrenceStatus.ACTIVE,
                QuestOccurrence.due_at.is_not(None),
                QuestOccurrence.due_at <= clock.now(),
            )
            .order_by(QuestOccurrence.id)
        )
    )
    await session.rollback()
    total = 0
    for occurrence_id in ids:
        try:
            if await _expire_one(session, occurrence_id):
                total += 1
        except Exception:
            await session.rollback()
            log.exception("expire_occurrences failed for occurrence %s", occurrence_id)
    if total:
        log.info("expire_occurrences expired %s occurrence(s)", total)
    return total
