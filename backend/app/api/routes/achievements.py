"""Achievements (ARCHITECTURE §5 ``GET /achievements``): the code-defined list with my progress
and my unlocks. Unlocking happens on commit (``achievements.service``), never through a route."""

from fastapi import APIRouter

from app.core.deps import CurrentUser, SessionDep
from app.modules.achievements import service
from app.modules.achievements.service import AchievementsOut

router = APIRouter(tags=["achievements"])


@router.get("/achievements", response_model=AchievementsOut)
async def list_achievements(user: CurrentUser, session: SessionDep) -> AchievementsOut:
    return await service.achievements(session, user)
