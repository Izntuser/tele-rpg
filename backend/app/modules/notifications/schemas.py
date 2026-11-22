"""Notification preferences and inbox schemas (ARCHITECTURE §5 notifications routes).

``user.notification_prefs`` (jsonb) stores a ``NotificationPrefs``; whatever is missing or
invalid there falls back to the defaults (every category on, quiet hours 23:00-08:00,
daily summary on; ARCHITECTURE §9 open question 6).
"""

from datetime import datetime
from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.common.enums import NotificationCategory

#: "HH:MM", 24-hour clock, in the user's own timezone.
ClockTime = Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]

DEFAULT_QUIET_START = "23:00"
DEFAULT_QUIET_END = "08:00"


def _all_categories() -> dict[NotificationCategory, bool]:
    return dict.fromkeys(NotificationCategory, True)


class NotificationPrefs(BaseModel):
    """Effective preferences. Quiet hours are off when start and end are both null."""

    model_config = ConfigDict(extra="ignore")

    categories: dict[NotificationCategory, bool] = Field(default_factory=_all_categories)
    quiet_hours_start: ClockTime | None = DEFAULT_QUIET_START
    quiet_hours_end: ClockTime | None = DEFAULT_QUIET_END
    daily_summary: bool = True

    @model_validator(mode="after")
    def _complete(self) -> Self:
        # Every category has a value; unknown keys were already rejected by the enum.
        self.categories = {**_all_categories(), **self.categories}
        if (self.quiet_hours_start is None) != (self.quiet_hours_end is None):
            raise ValueError("quiet_hours_start and quiet_hours_end are set or cleared together")
        return self

    def category_enabled(self, category: NotificationCategory) -> bool:
        return self.categories.get(category, True)


class PreferencesUpdate(BaseModel):
    """PATCH /notifications/preferences: omitted fields keep their value; categories merge.
    Send both quiet-hours fields as null to turn quiet hours off."""

    model_config = ConfigDict(extra="forbid")

    categories: dict[NotificationCategory, bool] | None = None
    quiet_hours_start: ClockTime | None = None
    quiet_hours_end: ClockTime | None = None
    daily_summary: bool | None = None


class PreferencesOut(NotificationPrefs):
    #: The user let the bot message them (Telegram ``requestWriteAccess``).
    can_message: bool


class WriteAccessIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed: bool


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    category: NotificationCategory
    entity_type: str | None
    entity_id: int | None
    payload: dict[str, Any]
    #: Telegram ``startapp`` value (``q_<id>``, ``qt_<id>``, ``r_<id>``, ...); the client maps
    #: it to a route with lib/deeplink.ts. Null opens Home.
    deep_link: str | None
    read_at: datetime | None
    created_at: datetime


class InboxOut(BaseModel):
    items: list[NotificationOut]
    #: Pass as ``cursor`` for the next (older) page; null on the last page.
    next_cursor: int | None
    unread_count: int


class UnreadCountOut(BaseModel):
    count: int


class ReadAllOut(BaseModel):
    updated: int
