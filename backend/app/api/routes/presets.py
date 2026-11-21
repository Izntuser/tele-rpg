"""Quest presets (built-in + my saved templates) and the gold estimate.

Registered before ``routes/quests.py`` (modules load in name order), so the fixed path
``/quests/estimate`` is matched before ``/quests/{occurrence_id}``.
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.core.deps import CurrentUser, SessionDep
from app.modules.common.enums import Recurrence
from app.modules.common.validation import IdPath
from app.modules.quests import presets
from app.modules.quests.schemas import GOLD_MAX, GOLD_MIN

router = APIRouter(tags=["quests"])


@router.get("/quests/estimate", response_model=presets.Estimate)
async def quest_estimate(
    _user: CurrentUser,
    gold: Annotated[int, Query(ge=GOLD_MIN, le=GOLD_MAX)],
    recurrence: Recurrence = Recurrence.ONCE,
) -> presets.Estimate:
    """Most Gold a quest could create per week and per month (inflation guidance)."""
    return presets.estimate(gold, recurrence)


@router.get("/quest-presets", response_model=presets.PresetList)
async def list_presets(user: CurrentUser, session: SessionDep) -> presets.PresetList:
    """Built-in presets in my language, plus my saved templates."""
    return await presets.list_presets(session, user)


@router.post(
    "/quest-presets", response_model=presets.PresetOut, status_code=status.HTTP_201_CREATED
)
async def save_preset(
    body: presets.PresetCreate, user: CurrentUser, session: SessionDep
) -> presets.PresetOut:
    try:
        return await presets.save_preset(session, user, body)
    except presets.TooManySavedError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Too many saved templates") from None


@router.delete("/quest-presets/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_preset(preset_id: IdPath, user: CurrentUser, session: SessionDep) -> Response:
    try:
        await presets.delete_preset(session, user, preset_id)
    except presets.PresetNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found") from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
