"""The caller's own character. There is no route that takes a character or user id: every
endpoint reads and writes the character of ``CurrentUser`` only."""

from fastapi import APIRouter, HTTPException, status

from app.core.deps import CurrentUser, SessionDep
from app.modules.users import service
from app.modules.users.schemas import CharacterOut, CharacterUpdate, OnboardingIn, OnboardingOut

router = APIRouter(prefix="/character", tags=["character"])


def _no_character() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Character not created yet")


@router.get("", response_model=CharacterOut)
async def get_character(user: CurrentUser, session: SessionDep) -> CharacterOut:
    try:
        return await service.read_character(session, user)
    except service.CharacterNotFoundError:
        raise _no_character() from None


@router.patch("", response_model=CharacterOut)
async def patch_character(
    body: CharacterUpdate, user: CurrentUser, session: SessionDep
) -> CharacterOut:
    """Edit name, nickname, bio, locale and timezone. Any other field (``total_xp``,
    ``level``, ``gold`` ...) is ignored."""
    try:
        return await service.update_character(session, user, body)
    except service.CharacterNotFoundError:
        raise _no_character() from None


@router.post("/onboarding/complete", response_model=OnboardingOut)
async def complete_onboarding(
    body: OnboardingIn, user: CurrentUser, session: SessionDep
) -> OnboardingOut:
    """Create the character with its 6 attributes and the chosen goals, set the timezone and
    mark the user onboarded. 409 if already onboarded."""
    try:
        return await service.complete_onboarding(session, user, body)
    except service.AlreadyOnboardedError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Already onboarded") from None
