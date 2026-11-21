"""My development goals. Reads may target the active companion (``?user=companion``); writes
only ever act on the caller's own goals (another user's id answers 404)."""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.core.deps import CurrentUser, SessionDep
from app.modules.common.validation import IdPath
from app.modules.goals import service
from app.modules.goals.schemas import GoalCreate, GoalOut, GoalUpdate
from app.modules.users.service import NotPartneredError, resolve_owner

router = APIRouter(prefix="/goals", tags=["goals"])

Who = Annotated[Literal["me", "companion"], Query(alias="user")]


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Goal not found")


@router.get("", response_model=list[GoalOut])
async def list_goals(user: CurrentUser, session: SessionDep, who: Who = "me") -> list[GoalOut]:
    """My goals (active and archived), or the active companion's active goals (403 when there
    is no active partnership)."""
    try:
        owner_id = await resolve_owner(session, user, who)
    except NotPartneredError:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No active partnership") from None
    goals = await service.list_goals(session, owner_id, include_archived=who == "me")
    return [GoalOut.model_validate(g) for g in goals]


@router.post("", response_model=GoalOut, status_code=status.HTTP_201_CREATED)
async def create_goal(body: GoalCreate, user: CurrentUser, session: SessionDep) -> GoalOut:
    try:
        goal = await service.create_goal(session, user, body)
    except service.GoalLimitError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Too many goals") from None
    return GoalOut.model_validate(goal)


@router.patch("/{goal_id}", response_model=GoalOut)
async def update_goal(
    goal_id: IdPath, body: GoalUpdate, user: CurrentUser, session: SessionDep
) -> GoalOut:
    try:
        goal = await service.update_goal(session, user, goal_id, body)
    except service.GoalNotFoundError:
        raise _not_found() from None
    return GoalOut.model_validate(goal)


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_goal(goal_id: IdPath, user: CurrentUser, session: SessionDep) -> Response:
    try:
        await service.delete_goal(session, user, goal_id)
    except service.GoalNotFoundError:
        raise _not_found() from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
