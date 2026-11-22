"""Partnership schemas.

Invite tokens are URL-safe base64 (``secrets.token_urlsafe``), so the accepted alphabet is the
one Telegram allows in a ``startapp`` parameter. Typed confirmations are fixed, locale-free
words that the UI shows and the user retypes.
"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.modules.common.enums import GoalStatus, WishlistStatus
from app.modules.users.schemas import AttributeOut

#: Text the user must type to leave a partnership.
LEAVE_CONFIRM_TEXT = "LEAVE"

InviteToken = Annotated[str, Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]


class InvitationCreated(BaseModel):
    """Returned once, on creation: only the sha256 of ``token`` is stored."""

    token: str
    link: str
    expires_at: datetime


class InvitationTokenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: InviteToken


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_text: str = Field(max_length=64)


class CompanionCard(BaseModel):
    """Public profile of another user: no Telegram id or username."""

    user_id: int
    display_name: str
    avatar_url: str | None
    #: Custom avatar; readable (``GET /files/{id}``) only by an active partner.
    avatar_file_id: int | None
    character_name: str | None
    nickname: str | None
    level: int


class InvitationPreview(BaseModel):
    inviter: CompanionCard
    expires_at: datetime


class PendingInvitationOut(BaseModel):
    expires_at: datetime


class ActivePartnershipOut(BaseModel):
    id: int
    accepted_at: datetime | None
    companion: CompanionCard


class PartnershipStateOut(BaseModel):
    partnership: ActivePartnershipOut | None
    pending_invitation: PendingInvitationOut | None


class AcceptOut(BaseModel):
    partnership: ActivePartnershipOut
    #: True when an earlier partnership of the same two users was reactivated.
    reactivated: bool


class CompanionGoalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    attribute: str | None
    status: GoalStatus


class CompanionWishOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    status: WishlistStatus


class CompanionProfileOut(BaseModel):
    card: CompanionCard
    bio: str | None
    total_xp: int
    xp_into_level: int
    xp_for_next_level: int
    attributes: list[AttributeOut]
    goals: list[CompanionGoalOut]
    wishlist: list[CompanionWishOut]
