"""Quest request/response schemas.

The client never sends XP, an assignee, a creator, a status or a partnership: XP comes from
``Settings.difficulty_xp``, the assignee is the active companion, and unknown input fields
(``xp`` among them) are ignored.
"""

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core import clock
from app.modules.common.enums import (
    Attribute,
    ConfirmationMode,
    Difficulty,
    QuestOccurrenceStatus,
    QuestRevisionStatus,
    QuestTemplateStatus,
    Recurrence,
    SubmissionReviewStatus,
)
from app.modules.common.validation import Description, Reason, RequiredReason, Title

GOLD_MIN = 0
GOLD_MAX = 1000
#: Open (offered, active or paused) templates one creator may have in a partnership.
MAX_OPEN_TEMPLATES = 100

Gold = Annotated[int, Field(ge=GOLD_MIN, le=GOLD_MAX)]
Role = Literal["player", "gm"]


def _future(value: datetime | None) -> datetime | None:
    if value is not None and value <= clock.now():
        raise ValueError("deadline must be in the future")
    return value


class QuestTerms(BaseModel):
    """The terms a player agrees to; stored as ``quest_revision.terms`` and copied into every
    occurrence's ``terms_snapshot``."""

    title: str
    description: str | None
    attribute: Attribute
    difficulty: Difficulty
    gold: int
    xp: int
    deadline: datetime | None
    confirmation: ConfirmationMode
    photo_required: bool

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class QuestCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: Title
    description: Description = None
    attribute: Attribute
    difficulty: Difficulty = Difficulty.NORMAL
    gold: Gold
    recurrence: Recurrence = Recurrence.ONCE
    deadline_at: AwareDatetime | None = None
    confirmation: ConfirmationMode = ConfirmationMode.MANUAL
    photo_required: bool = False

    @field_validator("deadline_at", mode="after")
    @classmethod
    def _deadline_future(cls, value: datetime | None) -> datetime | None:
        return _future(value)

    @model_validator(mode="after")
    def _deadline_only_once(self) -> "QuestCreate":
        if self.deadline_at is not None and self.recurrence != Recurrence.ONCE:
            raise ValueError("only one-time quests can have a deadline")
        return self


class QuestUpdate(BaseModel):
    """Changed terms. Omitted fields stay; ``description`` and ``deadline_at`` accept null to
    clear. The recurrence cannot be changed."""

    model_config = ConfigDict(extra="ignore")

    title: Title | None = None
    description: Description = None
    attribute: Attribute | None = None
    difficulty: Difficulty | None = None
    gold: Gold | None = None
    deadline_at: AwareDatetime | None = None
    confirmation: ConfirmationMode | None = None
    photo_required: bool | None = None

    @field_validator("deadline_at", mode="after")
    @classmethod
    def _deadline_future(cls, value: datetime | None) -> datetime | None:
        return _future(value)

    @field_validator(
        "title", "attribute", "difficulty", "gold", "confirmation", "photo_required", mode="after"
    )
    @classmethod
    def _not_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("cannot be null")
        return value


class DeclineIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reason: Reason = None


class SubmitIn(BaseModel):
    """The assignee's report. ``attachment_id`` must be a quest photo the assignee uploaded;
    a ``photo_required`` quest needs one."""

    model_config = ConfigDict(extra="ignore")

    comment: Description = None
    attachment_id: Annotated[int, Field(gt=0, le=2**63 - 1)] | None = None


class ConfirmIn(BaseModel):
    """Optional positive feedback from the creator."""

    model_config = ConfigDict(extra="ignore")

    feedback: Reason = None


class RedoIn(BaseModel):
    """Why the creator wants corrections: required, non-blank."""

    model_config = ConfigDict(extra="ignore")

    reason: RequiredReason


class RevisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version: int
    terms: QuestTerms
    status: QuestRevisionStatus
    proposed_by: int
    created_at: datetime
    decided_at: datetime | None
    #: The assignee's reason when it was declined; visible to both members, never copied into
    #: journal or notification payloads.
    decline_reason: str | None


class SubmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    submitted_by: int
    comment: str | None
    attachment_id: int | None
    created_at: datetime
    review_status: SubmissionReviewStatus
    review_comment: str | None
    reviewed_at: datetime | None


class StreakOut(BaseModel):
    """Consecutive completed days of a daily quest (display only)."""

    current: int
    best: int
    last_completed_date: date | None


class TemplateOut(BaseModel):
    id: int
    partnership_id: int
    creator_id: int
    assignee_id: int
    role: Role
    status: QuestTemplateStatus
    recurrence: Recurrence
    terms: QuestTerms
    version: int
    pending_revision: RevisionOut | None
    #: The newest declined revision (a declined offer, or a declined proposal not yet replaced
    #: by a newer accepted revision), with its decline_reason; null otherwise.
    last_declined_revision: RevisionOut | None
    #: Daily quests only (zeros before the first completion); null for other recurrences.
    streak: StreakOut | None = None
    created_at: datetime


class OccurrenceOut(BaseModel):
    id: int
    template_id: int
    creator_id: int
    assignee_id: int
    role: Role
    status: QuestOccurrenceStatus
    template_status: QuestTemplateStatus
    recurrence: Recurrence
    scheduled_date: date
    due_at: datetime | None
    terms: QuestTerms
    accepted_at: datetime | None
    submitted_at: datetime | None
    completed_at: datetime | None
    cancelled_by: int | None
    decline_reason: str | None
    has_pending_revision: bool


class OccurrenceDetail(OccurrenceOut):
    template: TemplateOut
    submissions: list[SubmissionOut]


class TemplateDetail(TemplateOut):
    latest_occurrence: OccurrenceOut | None


class QuestCreated(BaseModel):
    template: TemplateOut
    #: The offered occurrence of a one-time quest; null for a recurring offer, whose first
    #: occurrence is created when the assignee accepts.
    occurrence: OccurrenceOut | None


class CompletionOut(BaseModel):
    """What completing the occurrence awarded to its assignee (for the celebration)."""

    gold: int
    xp: int
    attribute: Attribute
    attribute_xp: int
    total_xp: int
    level_before: int
    level: int
    attribute_level_before: int
    attribute_level: int
    #: Wallet balance in the quest's partnership after the credit.
    balance: int


class QuestActionResult(OccurrenceDetail):
    """Response of submit / confirm / request-redo. ``completion`` is set when this request
    completed the occurrence (confirm, or submit of an auto-confirm quest)."""

    completion: CompletionOut | None = None
