"""Wishlist schemas. ``linked_reward_id`` and the ``offered`` status belong to the reward shop
and are never client-settable here (unknown input fields are ignored)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from app.modules.common.enums import WishlistStatus
from app.modules.common.validation import Description, Title

#: Per-user cap on stored wishlist items.
MAX_WISHLIST_ITEMS = 50


class WishlistItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    status: WishlistStatus
    linked_reward_id: int | None


class WishlistItemCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: Title
    description: Description = None


#: The statuses an owner may set; ``offered`` is set by the reward shop only.
EditableWishlistStatus = Literal["open", "archived"]


class WishlistItemUpdate(BaseModel):
    """Omitted fields are left alone; ``description`` accepts null to clear."""

    model_config = ConfigDict(extra="ignore")

    title: Title | None = None
    description: Description = None
    status: EditableWishlistStatus | None = None

    @field_validator("title", "status", mode="after")
    @classmethod
    def _not_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("cannot be null")
        return value
