"""Pairing and the companion. Tokens travel only in JSON bodies (never in a URL, so access logs
never see them), and no route takes a user or partnership id: everything acts on the caller."""

from fastapi import APIRouter, HTTPException, Response, status

from app.core.deps import CurrentUser, SessionDep, SettingsDep
from app.modules.partnerships import service
from app.modules.partnerships.schemas import (
    AcceptOut,
    CompanionProfileOut,
    ConfirmIn,
    InvitationCreated,
    InvitationPreview,
    InvitationTokenIn,
    PartnershipStateOut,
)

router = APIRouter(prefix="/partnership", tags=["partnership"])

_ERRORS: dict[type[service.PartnershipError], tuple[int, str]] = {
    service.InvitationNotFoundError: (status.HTTP_404_NOT_FOUND, "Invitation not found"),
    service.InvitationExpiredError: (status.HTTP_410_GONE, "Invitation expired"),
    service.InvitationUsedError: (status.HTTP_410_GONE, "Invitation is no longer valid"),
    service.OwnInvitationError: (status.HTTP_409_CONFLICT, "You cannot accept your own invitation"),
    service.AlreadyPartneredError: (status.HTTP_409_CONFLICT, "Already in a partnership"),
    service.NotOnboardedError: (status.HTTP_409_CONFLICT, "Complete onboarding first"),
    service.NotPartneredError: (status.HTTP_403_FORBIDDEN, "No active partnership"),
    service.WrongConfirmationError: (status.HTTP_400_BAD_REQUEST, "Confirmation text mismatch"),
    service.InviteLinkNotConfiguredError: (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Invite links are not configured",
    ),
}


def _http(exc: service.PartnershipError) -> HTTPException:
    code, detail = _ERRORS[type(exc)]
    return HTTPException(code, detail)


@router.post("/invitations", response_model=InvitationCreated, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    user: CurrentUser, session: SessionDep, settings: SettingsDep, response: Response
) -> InvitationCreated:
    """New invite link (revokes my previous pending one). The token is shown only here."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return await service.create_invitation(session, user, settings)
    except service.PartnershipError as exc:
        raise _http(exc) from None


@router.delete("/invitations/current", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(user: CurrentUser, session: SessionDep) -> Response:
    await service.revoke_invitation(session, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/invitations/preview", response_model=InvitationPreview)
async def preview_invitation(
    body: InvitationTokenIn, user: CurrentUser, session: SessionDep
) -> InvitationPreview:
    """Who invited me (for the accept screen); same validity rules as accept."""
    try:
        return await service.preview_invitation(session, user, body.token)
    except service.PartnershipError as exc:
        raise _http(exc) from None


@router.post("/invitations/accept", response_model=AcceptOut)
async def accept_invitation(
    body: InvitationTokenIn, user: CurrentUser, session: SessionDep
) -> AcceptOut:
    try:
        return await service.accept_invitation(session, user, body.token)
    except service.PartnershipError as exc:
        raise _http(exc) from None


@router.get("", response_model=PartnershipStateOut)
async def get_partnership(user: CurrentUser, session: SessionDep) -> PartnershipStateOut:
    return await service.state(session, user)


@router.get("/companion", response_model=CompanionProfileOut)
async def get_companion(user: CurrentUser, session: SessionDep) -> CompanionProfileOut:
    try:
        return await service.companion_profile(session, user)
    except service.PartnershipError as exc:
        raise _http(exc) from None


@router.post("/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave(body: ConfirmIn, user: CurrentUser, session: SessionDep) -> Response:
    try:
        await service.leave(session, user, body.confirm_text)
    except service.PartnershipError as exc:
        raise _http(exc) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
