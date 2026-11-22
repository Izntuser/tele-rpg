"""Achievement evaluation and reads.

``journal.service.record_event`` notes ``(actor, partnership) -> {event types}`` in
``session.info``. Right before the transaction commits, ``_evaluate_pending`` (a
``before_commit`` listener on every Session) flushes, then evaluates each definition whose
triggers were recorded, for the actor and for both members of the event's partnership (a
companion's event can move my metric, e.g. ``mentor`` counts quests I created that my
companion completed). The unlock is ``INSERT ... ON CONFLICT DO NOTHING`` on the
``(user_id, code)`` primary key, so each achievement unlocks exactly once even when two
transactions race; only the inserting transaction writes the ``achievement_unlocked`` journal
event (shared, no names in the payload). A rollback discards the notes.

Listeners run inside the sync commit, which an ``AsyncSession`` drives in a greenlet, so the
plain ``Session.execute`` calls here are fine.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import event, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.modules.achievements.definitions import ACHIEVEMENTS, TRIGGER_TYPES
from app.modules.achievements.models import AchievementUnlock
from app.modules.journal.service import PENDING_ACHIEVEMENTS, record_event
from app.modules.partnerships.models import Partnership
from app.modules.users.models import User

UNLOCK_EVENT = "achievement_unlocked"


class AchievementOut(BaseModel):
    code: str
    icon: str
    target: int
    #: Current value of the metric, capped at ``target``.
    progress: int
    unlocked_at: datetime | None


class UnlockOut(BaseModel):
    code: str
    unlocked_at: datetime


class AchievementsOut(BaseModel):
    definitions: list[AchievementOut]
    unlocks: list[UnlockOut]


def _unlocked_codes(session: Session, user_id: int) -> set[str]:
    return set(
        session.scalars(select(AchievementUnlock.code).where(AchievementUnlock.user_id == user_id))
    )


def evaluate(
    session: Session, user_id: int, types: set[str], partnership_id: int | None
) -> list[str]:
    """Unlock every definition triggered by ``types`` whose target ``user_id`` has reached;
    returns the codes this call unlocked. Deleted users never unlock anything."""
    user = session.get(User, user_id)
    if user is None or user.deleted_at is not None:
        return []
    have = _unlocked_codes(session, user_id)
    unlocked: list[str] = []
    for definition in ACHIEVEMENTS:
        if definition.code in have or not (definition.triggers & types):
            continue
        if definition.metric(session, user_id) < definition.target:
            continue
        inserted = session.scalar(
            insert(AchievementUnlock)
            .values(user_id=user_id, code=definition.code)
            .on_conflict_do_nothing(index_elements=["user_id", "code"])
            .returning(AchievementUnlock.code)
        )
        if inserted is None:
            continue
        unlocked.append(definition.code)
        record_event(
            session,
            user_id=user_id,
            type=UNLOCK_EVENT,
            partnership_id=partnership_id,
            entity_type="achievement",
            entity_id=None,
            payload={"code": definition.code},
        )
    return unlocked


@event.listens_for(Session, "before_commit")
def _evaluate_pending(session: Session) -> None:
    pending: dict[tuple[int, int | None], set[str]] | None = session.info.pop(
        PENDING_ACHIEVEMENTS, None
    )
    if not pending:
        return
    targets: dict[tuple[int, int | None], set[str]] = {}
    for (actor_id, partnership_id), types in pending.items():
        relevant = types & TRIGGER_TYPES
        if not relevant:
            continue
        members = {actor_id}
        if partnership_id is not None:
            partnership = session.get(Partnership, partnership_id)
            if partnership is not None:
                members |= {partnership.user_a_id, partnership.user_b_id}
        for member in members:
            targets.setdefault((member, partnership_id), set()).update(relevant)
    if not targets:
        return
    session.flush()
    for (user_id, partnership_id), types in sorted(targets.items(), key=lambda kv: kv[0][0]):
        evaluate(session, user_id, types, partnership_id)
    # The unlock events were noted too; they trigger nothing, so drop the note.
    session.info.pop(PENDING_ACHIEVEMENTS, None)


@event.listens_for(Session, "after_soft_rollback")
def _discard_pending(session: Session, previous_transaction: Any) -> None:
    session.info.pop(PENDING_ACHIEVEMENTS, None)


def _read(session: Session, user_id: int) -> AchievementsOut:
    rows = session.execute(
        select(AchievementUnlock.code, AchievementUnlock.unlocked_at)
        .where(AchievementUnlock.user_id == user_id)
        .order_by(AchievementUnlock.unlocked_at, AchievementUnlock.code)
    ).all()
    unlocked = {code: at for code, at in rows}
    return AchievementsOut(
        definitions=[
            AchievementOut(
                code=a.code,
                icon=a.icon,
                target=a.target,
                progress=a.target
                if a.code in unlocked
                else min(a.target, a.metric(session, user_id)),
                unlocked_at=unlocked.get(a.code),
            )
            for a in ACHIEVEMENTS
        ],
        unlocks=[UnlockOut(code=code, unlocked_at=at) for code, at in rows],
    )


async def achievements(session: AsyncSession, user: User) -> AchievementsOut:
    """Every definition with my progress, plus my unlocks (oldest first)."""
    user_id = user.id
    return await session.run_sync(lambda s: _read(s, user_id))
