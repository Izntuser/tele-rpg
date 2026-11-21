"""Daily-quest streaks (display only): consecutive completed days, by scheduled date.

``record_completion`` moves a streak forward when an occurrence is confirmed; ``break_streak``
resets ``current`` when a day is missed (the expiry job calls it). ``best`` never goes down.
Both lock the ``quest_streak`` row, the last lock in the documented order.
"""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.quests.models import QuestStreak


async def _locked(session: AsyncSession, template_id: int) -> QuestStreak:
    await session.execute(
        insert(QuestStreak)
        .values(template_id=template_id, current=0, best=0)
        .on_conflict_do_nothing(index_elements=[QuestStreak.template_id])
    )
    streak = await session.scalar(
        select(QuestStreak)
        .where(QuestStreak.template_id == template_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert streak is not None
    return streak


async def record_completion(session: AsyncSession, template_id: int, day: date) -> None:
    """Daily quests only: completing ``day`` extends the streak when it follows the last
    completed day, else restarts it at 1. Completing an older day late (a slow review) never
    moves the streak backwards."""
    streak = await _locked(session, template_id)
    last = streak.last_completed_date
    if last is not None and day <= last:
        return
    consecutive = last is not None and last + timedelta(days=1) == day
    streak.current = streak.current + 1 if consecutive else 1
    streak.best = max(streak.best, streak.current)
    streak.last_completed_date = day


async def break_streak(session: AsyncSession, template_id: int, missed_day: date) -> None:
    """``missed_day`` expired uncompleted: the current streak is over. A day at or before the
    last completed one changes nothing."""
    streak = await _locked(session, template_id)
    if streak.last_completed_date is not None and missed_day <= streak.last_completed_date:
        return
    streak.current = 0
