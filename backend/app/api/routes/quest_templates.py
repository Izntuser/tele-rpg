"""Pause and resume a recurring quest (creator only). The rest of ``/quest-templates`` lives in
``quests.py``."""

from fastapi import APIRouter

from app.api.routes.quests import _http
from app.core.deps import CurrentUser, SessionDep
from app.modules.common.validation import IdPath
from app.modules.quests import service
from app.modules.quests.schemas import TemplateDetail

router = APIRouter(tags=["quests"])


async def _set_paused(
    template_id: int, user: CurrentUser, session: SessionDep, *, paused: bool
) -> TemplateDetail:
    try:
        await service.set_paused(session, user, template_id, paused=paused)
        return await service.get_template(session, user, template_id)
    except service.QuestError as exc:
        await session.rollback()
        raise _http(exc) from None


@router.post("/quest-templates/{template_id}/pause", response_model=TemplateDetail)
async def pause_quest_template(
    template_id: IdPath, user: CurrentUser, session: SessionDep
) -> TemplateDetail:
    """Creator: stop generating new occurrences of a recurring quest."""
    return await _set_paused(template_id, user, session, paused=True)


@router.post("/quest-templates/{template_id}/resume", response_model=TemplateDetail)
async def resume_quest_template(
    template_id: IdPath, user: CurrentUser, session: SessionDep
) -> TemplateDetail:
    """Creator: restart generation; the current period's occurrence is created at once."""
    return await _set_paused(template_id, user, session, paused=False)
