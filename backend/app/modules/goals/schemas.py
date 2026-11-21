"""Development goal schemas. ``id``, ``user_id`` and ``created_at`` are never client-settable
(unknown input fields are ignored)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from app.modules.common.enums import Attribute, GoalStatus
from app.modules.common.validation import Description, Title

#: Per-user cap on stored goals (active + archived).
MAX_GOALS = 50


class GoalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    attribute: Attribute | None
    status: GoalStatus
    created_at: datetime


class GoalCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: Title
    description: Description = None
    attribute: Attribute | None = None


class GoalUpdate(BaseModel):
    """Omitted fields are left alone; ``description``/``attribute`` accept null to clear."""

    model_config = ConfigDict(extra="ignore")

    title: Title | None = None
    description: Description = None
    attribute: Attribute | None = None
    status: GoalStatus | None = None

    @field_validator("title", "status", mode="after")
    @classmethod
    def _not_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("cannot be null")
        return value
