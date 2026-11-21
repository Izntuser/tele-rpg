"""Create the current period's occurrence of every active daily / weekly quest.

The period is computed in the assignee's timezone: today for a daily quest, the ISO week's
Monday for a weekly one. Only the current period is ever created (no backfill after downtime),
paused / cancelled templates and ended partnerships are skipped, and
``ensure_occurrence`` is idempotent, so running the job again or after a restart never
duplicates. Each template is its own transaction, in the documented lock order (partnership
``FOR SHARE``, then template).
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.modules.common.enums import PartnershipStatus, QuestTemplateStatus, Recurrence
from app.modules.partnerships.models import Partnership
from app.modules.quests.models import QuestTemplate
from app.modules.quests.occurrences import TemplateNotSchedulableError, ensure_occurrence
from app.modules.users.models import User

log = logging.getLogger(__name__)


async def _generate_one(session: AsyncSession, template_id: int, partnership_id: int) -> bool:
    partnership = await session.scalar(
        select(Partnership)
        .where(Partnership.id == partnership_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    template = await session.scalar(
        select(QuestTemplate)
        .where(QuestTemplate.id == template_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    created = False
    if (
        partnership is not None
        and partnership.status == PartnershipStatus.ACTIVE
        and template is not None
        and template.status == QuestTemplateStatus.ACTIVE
    ):
        assignee = await session.get(User, template.assignee_id)
        if assignee is not None and assignee.deleted_at is None:
            try:
                _, created = await ensure_occurrence(session, template, assignee.timezone)
            except TemplateNotSchedulableError:  # pragma: no cover - status checked above
                created = False
    await session.commit()
    return created


async def run(session: AsyncSession) -> int:
    """Generate what is missing; returns how many occurrences were created."""
    rows = (
        await session.execute(
            select(QuestTemplate.id, QuestTemplate.partnership_id).where(
                QuestTemplate.status == QuestTemplateStatus.ACTIVE,
                QuestTemplate.recurrence.in_([Recurrence.DAILY, Recurrence.WEEKLY]),
            )
        )
    ).all()
    await session.rollback()  # end the read transaction before the per-template ones
    total = 0
    for template_id, partnership_id in rows:
        try:
            if await _generate_one(session, template_id, partnership_id):
                total += 1
        except Exception:
            await session.rollback()
            log.exception("generate_occurrences failed for template %s", template_id)
    if total:
        log.info("generate_occurrences created %s occurrence(s) at %s", total, clock.now())
    return total
