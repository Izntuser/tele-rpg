"""Development goals ("I Want to Improve").

Writes only ever touch rows whose ``user_id`` is the caller: an item id that belongs to
someone else is indistinguishable from a missing one (GoalNotFoundError -> 404).
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.common.enums import GoalStatus
from app.modules.goals.models import DevelopmentGoal
from app.modules.goals.schemas import MAX_GOALS, GoalCreate, GoalUpdate
from app.modules.users.models import User
from app.modules.users.service import lock_user


class GoalNotFoundError(Exception):
    pass


class GoalLimitError(Exception):
    pass


async def list_goals(
    session: AsyncSession, owner_id: int, *, include_archived: bool
) -> list[DevelopmentGoal]:
    query = select(DevelopmentGoal).where(DevelopmentGoal.user_id == owner_id)
    if not include_archived:
        query = query.where(DevelopmentGoal.status == GoalStatus.ACTIVE)
    result = await session.scalars(query.order_by(DevelopmentGoal.id))
    return list(result)


async def create_goal(session: AsyncSession, user: User, data: GoalCreate) -> DevelopmentGoal:
    await lock_user(session, user.id)
    count = await session.scalar(
        select(func.count()).select_from(DevelopmentGoal).where(DevelopmentGoal.user_id == user.id)
    )
    if (count or 0) >= MAX_GOALS:
        raise GoalLimitError
    goal = DevelopmentGoal(
        user_id=user.id,
        title=data.title,
        description=data.description,
        attribute=data.attribute,
    )
    session.add(goal)
    await session.commit()
    await session.refresh(goal)
    return goal


async def _own_goal(session: AsyncSession, user: User, goal_id: int) -> DevelopmentGoal:
    goal: DevelopmentGoal | None = await session.scalar(
        select(DevelopmentGoal)
        .where(DevelopmentGoal.id == goal_id, DevelopmentGoal.user_id == user.id)
        .with_for_update()
    )
    if goal is None:
        raise GoalNotFoundError
    return goal


async def update_goal(
    session: AsyncSession, user: User, goal_id: int, data: GoalUpdate
) -> DevelopmentGoal:
    goal = await _own_goal(session, user, goal_id)
    sent = data.model_fields_set
    if "title" in sent and data.title is not None:
        goal.title = data.title
    if "description" in sent:
        goal.description = data.description
    if "attribute" in sent:
        goal.attribute = data.attribute
    if "status" in sent and data.status is not None:
        goal.status = data.status
    await session.commit()
    return goal


async def delete_goal(session: AsyncSession, user: User, goal_id: int) -> None:
    goal = await _own_goal(session, user, goal_id)
    await session.delete(goal)
    await session.commit()
