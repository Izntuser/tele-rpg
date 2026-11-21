"""Quest offer flow routes. Thin: parse, call ``quests.service``, map its errors.

``/quests/{occurrence_id}`` addresses an occurrence (a one-time quest, or one day / week of a
recurring one). ``/quest-templates/{template_id}`` addresses the quest itself, which is how a
recurring offer (no occurrence until it is accepted) is accepted, declined, edited or
cancelled. Neither path ever takes a user or partnership id: the caller is the only subject.
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import idempotency
from app.core.deps import CurrentUser, SessionDep, SettingsDep
from app.modules.common.enums import QuestOccurrenceStatus, QuestTemplateStatus, Recurrence
from app.modules.common.validation import IdPath
from app.modules.quests import completion, service
from app.modules.quests.schemas import (
    ConfirmIn,
    DeclineIn,
    OccurrenceDetail,
    OccurrenceOut,
    QuestActionResult,
    QuestCreate,
    QuestCreated,
    QuestUpdate,
    RedoIn,
    Role,
    SubmitIn,
    TemplateDetail,
    TemplateOut,
)

router = APIRouter(tags=["quests"])

_ERRORS: dict[type[service.QuestError], tuple[int, str]] = {
    service.QuestNotFoundError: (status.HTTP_404_NOT_FOUND, "Quest not found"),
    service.WrongRoleError: (status.HTTP_403_FORBIDDEN, "Not allowed for your role"),
    service.NotPartneredError: (status.HTTP_403_FORBIDDEN, "No active partnership"),
    service.PartnershipInactiveError: (status.HTTP_409_CONFLICT, "Partnership has ended"),
    service.TooManyQuestsError: (status.HTTP_409_CONFLICT, "Too many open quests"),
    service.DeadlineNotAllowedError: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "Only one-time quests can have a deadline",
    ),
    service.InvalidAttachmentError: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "attachment_id must be a quest photo you uploaded",
    ),
    service.PhotoRequiredError: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "This quest requires a photo",
    ),
}
KEY_REUSED_DETAIL = "Idempotency-Key was already used for a different request"

Limit = Annotated[int, Query(ge=1, le=service.LIST_LIMIT_MAX)]


def _http(exc: service.QuestError) -> HTTPException:
    if isinstance(exc, service.QuestStateError):
        return HTTPException(status.HTTP_409_CONFLICT, exc.message)
    code, detail = _ERRORS[type(exc)]
    return HTTPException(code, detail)


# --- occurrences -----------------------------------------------------------------------------


@router.get("/quests", response_model=list[OccurrenceOut])
async def list_quests(
    user: CurrentUser,
    session: SessionDep,
    role: Role | None = None,
    quest_status: Annotated[list[QuestOccurrenceStatus] | None, Query(alias="status")] = None,
    limit: Limit = 100,
) -> list[OccurrenceOut]:
    """Occurrences in my active partnership. ``role=player``: assigned to me; ``role=gm``:
    created by me. ``status`` may repeat. Empty without an active partnership."""
    return await service.list_occurrences(
        session, user, role=role, statuses=quest_status or [], limit=limit
    )


@router.post("/quests", response_model=QuestCreated, status_code=status.HTTP_201_CREATED)
async def create_quest(
    body: QuestCreate, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> QuestCreated:
    """Offer a quest to my companion. XP comes from the difficulty; a client ``xp`` is
    ignored."""
    try:
        return await service.create(session, user, settings, body)
    except service.QuestError as exc:
        raise _http(exc) from None


@router.get("/quests/{occurrence_id}", response_model=OccurrenceDetail)
async def get_quest(
    occurrence_id: IdPath, user: CurrentUser, session: SessionDep
) -> OccurrenceDetail:
    try:
        return await service.get_occurrence(session, user, occurrence_id)
    except service.QuestError as exc:
        raise _http(exc) from None


@router.patch("/quests/{occurrence_id}", response_model=OccurrenceDetail)
async def update_quest(
    occurrence_id: IdPath,
    body: QuestUpdate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> OccurrenceDetail:
    """Creator: edit an offered quest in place, or propose a revision of an accepted one."""
    try:
        await service.update(session, user, settings, body, occurrence_id=occurrence_id)
        return await service.get_occurrence(session, user, occurrence_id)
    except service.QuestError as exc:
        raise _http(exc) from None


@router.post("/quests/{occurrence_id}/accept", response_model=OccurrenceDetail)
async def accept_quest(
    occurrence_id: IdPath, user: CurrentUser, session: SessionDep
) -> OccurrenceDetail:
    """Assignee: accept the offer, or the pending revision."""
    try:
        await service.accept(session, user, occurrence_id=occurrence_id)
        return await service.get_occurrence(session, user, occurrence_id)
    except service.QuestError as exc:
        raise _http(exc) from None


@router.post("/quests/{occurrence_id}/decline", response_model=OccurrenceDetail)
async def decline_quest(
    occurrence_id: IdPath, user: CurrentUser, session: SessionDep, body: DeclineIn | None = None
) -> OccurrenceDetail:
    """Assignee: decline the offer, or the pending revision (reason optional)."""
    try:
        await service.decline(
            session, user, body.reason if body else None, occurrence_id=occurrence_id
        )
        return await service.get_occurrence(session, user, occurrence_id)
    except service.QuestError as exc:
        raise _http(exc) from None


@router.post("/quests/{occurrence_id}/cancel", response_model=OccurrenceDetail)
async def cancel_quest(
    occurrence_id: IdPath, user: CurrentUser, session: SessionDep
) -> OccurrenceDetail:
    """Either member: cancel an offered or active occurrence."""
    try:
        await service.cancel(session, user, occurrence_id=occurrence_id)
        return await service.get_occurrence(session, user, occurrence_id)
    except service.QuestError as exc:
        raise _http(exc) from None


# --- completion ------------------------------------------------------------------------------


async def _claim(
    session: AsyncSession, user_id: int, key: str | None, endpoint: str, body: SubmitIn | ConfirmIn
) -> idempotency.Claim | idempotency.Replay | None:
    if key is None:
        return None
    try:
        return await idempotency.claim(
            session,
            user_id=user_id,
            key=key,
            endpoint=endpoint,
            request_hash=idempotency.fingerprint(body.model_dump(mode="json")),
        )
    except idempotency.IdempotencyKeyReusedError:
        await session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, KEY_REUSED_DETAIL) from None


@router.post(
    "/quests/{occurrence_id}/submit",
    response_model=QuestActionResult,
    responses={422: {"description": "Invalid body, attachment, or a reused Idempotency-Key"}},
)
async def submit_quest(
    occurrence_id: IdPath,
    user: CurrentUser,
    session: SessionDep,
    idempotency_key: idempotency.IdempotencyKeyHeader = None,
    body: SubmitIn | None = None,
) -> QuestActionResult | JSONResponse:
    """Assignee: submit an active quest (comment and photo optional unless photo_required). An
    auto-confirm quest is completed and paid out at once (``completion`` is set)."""
    data = body or SubmitIn()
    claim = await _claim(session, user.id, idempotency_key, f"quests/{occurrence_id}/submit", data)
    if isinstance(claim, idempotency.Replay):
        return claim.response()
    try:
        return await completion.submit(session, user, occurrence_id, data, idempotency=claim)
    except service.QuestError as exc:
        await session.rollback()
        raise _http(exc) from None


@router.post(
    "/quests/{occurrence_id}/confirm",
    response_model=QuestActionResult,
    responses={422: {"description": "Invalid body or a reused Idempotency-Key"}},
)
async def confirm_quest(
    occurrence_id: IdPath,
    user: CurrentUser,
    session: SessionDep,
    idempotency_key: idempotency.IdempotencyKeyHeader = None,
    body: ConfirmIn | None = None,
) -> QuestActionResult | JSONResponse:
    """Creator: confirm an in-review quest; Gold and XP from its accepted terms are awarded
    exactly once."""
    data = body or ConfirmIn()
    claim = await _claim(session, user.id, idempotency_key, f"quests/{occurrence_id}/confirm", data)
    if isinstance(claim, idempotency.Replay):
        return claim.response()
    try:
        return await completion.confirm(session, user, occurrence_id, data, idempotency=claim)
    except service.QuestError as exc:
        await session.rollback()
        raise _http(exc) from None


@router.post("/quests/{occurrence_id}/request-redo", response_model=QuestActionResult)
async def request_redo_quest(
    occurrence_id: IdPath, body: RedoIn, user: CurrentUser, session: SessionDep
) -> QuestActionResult:
    """Creator: send an in-review quest back to the player with a (required) reason."""
    try:
        return await completion.request_redo(session, user, occurrence_id, body)
    except service.QuestError as exc:
        await session.rollback()
        raise _http(exc) from None


# --- templates -------------------------------------------------------------------------------


@router.get("/quest-templates", response_model=list[TemplateOut])
async def list_quest_templates(
    user: CurrentUser,
    session: SessionDep,
    role: Role | None = None,
    template_status: Annotated[list[QuestTemplateStatus] | None, Query(alias="status")] = None,
    recurrence: Recurrence | None = None,
    limit: Limit = 100,
) -> list[TemplateOut]:
    """Quests (templates) in my active partnership, e.g. recurring offers."""
    return await service.list_templates(
        session,
        user,
        role=role,
        statuses=template_status or [],
        recurrence=recurrence,
        limit=limit,
    )


@router.get("/quest-templates/{template_id}", response_model=TemplateDetail)
async def get_quest_template(
    template_id: IdPath, user: CurrentUser, session: SessionDep
) -> TemplateDetail:
    try:
        return await service.get_template(session, user, template_id)
    except service.QuestError as exc:
        raise _http(exc) from None


@router.patch("/quest-templates/{template_id}", response_model=TemplateDetail)
async def update_quest_template(
    template_id: IdPath,
    body: QuestUpdate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> TemplateDetail:
    try:
        await service.update(session, user, settings, body, template_id=template_id)
        return await service.get_template(session, user, template_id)
    except service.QuestError as exc:
        raise _http(exc) from None


@router.post("/quest-templates/{template_id}/accept", response_model=TemplateDetail)
async def accept_quest_template(
    template_id: IdPath, user: CurrentUser, session: SessionDep
) -> TemplateDetail:
    """Assignee: accept the offer (a recurring one gets today's occurrence) or the pending
    revision."""
    try:
        await service.accept(session, user, template_id=template_id)
        return await service.get_template(session, user, template_id)
    except service.QuestError as exc:
        raise _http(exc) from None


@router.post("/quest-templates/{template_id}/decline", response_model=TemplateDetail)
async def decline_quest_template(
    template_id: IdPath, user: CurrentUser, session: SessionDep, body: DeclineIn | None = None
) -> TemplateDetail:
    try:
        await service.decline(session, user, body.reason if body else None, template_id=template_id)
        return await service.get_template(session, user, template_id)
    except service.QuestError as exc:
        raise _http(exc) from None


@router.post("/quest-templates/{template_id}/cancel", response_model=TemplateDetail)
async def cancel_quest_template(
    template_id: IdPath, user: CurrentUser, session: SessionDep
) -> TemplateDetail:
    """Either member: cancel the quest and its offered or active occurrences."""
    try:
        await service.cancel(session, user, template_id=template_id)
        return await service.get_template(session, user, template_id)
    except service.QuestError as exc:
        raise _http(exc) from None
