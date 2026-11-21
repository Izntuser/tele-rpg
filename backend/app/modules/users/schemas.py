"""Character and profile schemas.

Inputs use ``extra="ignore"``: fields the client must never set (``total_xp``, ``level``,
``gold``, ``user_id``, ``onboarded_at`` ...) are dropped, never applied. Outputs carry the
derived level numbers computed by ``app.modules.progression.levels``.
"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.auth.schemas import UserOut
from app.modules.common.enums import Attribute, Locale
from app.modules.common.validation import Bio, Name, Nickname, Timezone, Title

MAX_ONBOARDING_GOALS = 10


class AttributeOut(BaseModel):
    attribute: Attribute
    xp: int
    level: int
    xp_into_level: int
    xp_for_next_level: int


class CharacterOut(BaseModel):
    id: int
    name: str
    nickname: str | None
    bio: str | None
    avatar_url: str | None
    level: int
    total_xp: int
    #: XP earned inside the current level.
    xp_into_level: int
    #: Size of the current level (XP between this level's and the next level's threshold).
    xp_for_next_level: int
    #: XP still missing to reach the next level.
    xp_to_next_level: int
    attributes: list[AttributeOut]
    #: Balance of the wallet of the active partnership; 0 without one.
    gold: int
    locale: Locale
    timezone: str
    onboarded_at: datetime | None


class CharacterUpdate(BaseModel):
    """PATCH /character. Omitted fields are left alone; ``nickname``/``bio`` accept null or ""
    to clear. ``name``, ``locale`` and ``timezone`` cannot be cleared."""

    model_config = ConfigDict(extra="ignore")

    name: Name | None = None
    nickname: Nickname = None
    bio: Bio = None
    locale: Locale | None = None
    timezone: Timezone | None = None

    @field_validator("name", "locale", "timezone", mode="after")
    @classmethod
    def _not_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("cannot be null")
        return value


class OnboardingGoal(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: Title
    attribute: Attribute | None = None


class OnboardingIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: Name
    nickname: Nickname = None
    bio: Bio = None
    timezone: Timezone
    goals: Annotated[list[OnboardingGoal], Field(max_length=MAX_ONBOARDING_GOALS)] = []


class OnboardingOut(BaseModel):
    user: UserOut
    character: CharacterOut
