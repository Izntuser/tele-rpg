"""Reward shop and inventory schemas.

Request schemas ignore unknown fields, so a client can never set ``creator_id``,
``partnership_id``, ``quantity_remaining``, ``hidden_by_partnership_end``, ``sold_out``, a price
paid or a snapshot: those are server-owned. ``status`` in a request is the creator's
availability (``active`` / ``hidden``); ``sold_out`` is derived from the quantity.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.common.enums import RewardPurchaseStatus, RewardStatus
from app.modules.common.validation import MAX_BIGINT, Description, Reason, Title

#: Per-creator cap on rewards in one partnership's shop (hidden ones included).
MAX_REWARDS = 100
MAX_PRICE = 100_000
MAX_QUANTITY = 1_000
MAX_COOLDOWN_DAYS = 365
LIST_LIMIT_MAX = 100

Price = Annotated[int, Field(ge=1, le=MAX_PRICE)]
QuantityLimit = Annotated[int, Field(ge=1, le=MAX_QUANTITY)]
CooldownDays = Annotated[int, Field(ge=0, le=MAX_COOLDOWN_DAYS)]
#: The availability a creator sets; ``sold_out`` is derived.
Availability = Literal["active", "hidden"]
Shop = Literal["companion", "mine"]
Side = Literal["buyer", "provider"]


class RewardCreate(BaseModel):
    """A new reward in my shop. With ``wishlist_item_id`` (an open item on my companion's
    wishlist) ``title`` / ``description`` default to the item's."""

    model_config = ConfigDict(extra="ignore")

    title: Title | None = None
    description: Description = None
    price: Price
    quantity_limit: QuantityLimit | None = None
    cooldown_days: CooldownDays | None = None
    status: Availability = "active"
    wishlist_item_id: Annotated[int, Field(gt=0, le=MAX_BIGINT)] | None = None

    @model_validator(mode="after")
    def _title_or_wishlist_item(self) -> "RewardCreate":
        if self.title is None and self.wishlist_item_id is None:
            raise ValueError("title is required unless wishlist_item_id is given")
        return self


class RewardUpdate(BaseModel):
    """Omitted fields are left alone. ``description``, ``quantity_limit`` and ``cooldown_days``
    accept null to clear. Only future purchases are affected."""

    model_config = ConfigDict(extra="ignore")

    title: Title | None = None
    description: Description = None
    price: Price | None = None
    quantity_limit: QuantityLimit | None = None
    cooldown_days: CooldownDays | None = None
    status: Availability | None = None

    @field_validator("title", "price", "status", mode="after")
    @classmethod
    def _not_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("cannot be null")
        return value


class RewardOut(BaseModel):
    id: int
    creator_id: int
    title: str
    description: str | None
    price: int
    image_file_id: int | None
    quantity_limit: int | None
    quantity_remaining: int | None
    cooldown_days: int | None
    status: RewardStatus
    source_wishlist_item_id: int | None
    mine: bool
    #: For a companion's reward: until when my cooldown blocks buying it again (else null).
    cooldown_until: datetime | None
    created_at: datetime
    updated_at: datetime


class RewardSnapshot(BaseModel):
    """The reward as it was when bought; later edits never change it."""

    model_config = ConfigDict(extra="ignore")

    reward_id: int
    title: str
    description: str | None
    price: int
    image_file_id: int | None
    cooldown_days: int | None
    quantity_limit: int | None

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class ScheduleIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scheduled_for: AwareDatetime
    note: Reason = None


class PurchaseOut(BaseModel):
    """A voucher in my inventory (``side=buyer``) or one I must provide (``side=provider``)."""

    id: int
    reward_id: int
    buyer_id: int
    provider_id: int
    side: Side
    price_paid: int
    reward: RewardSnapshot
    status: RewardPurchaseStatus
    scheduled_for: datetime | None
    schedule_note: str | None
    purchased_at: datetime
    requested_at: datetime | None
    scheduled_at: datetime | None
    fulfilled_at: datetime | None
    disputed_at: datetime | None
    refunded_at: datetime | None
    refunded_by: int | None
    #: The partnership has ended: only a refund is still possible.
    frozen: bool
    #: Last moment the buyer may dispute a fulfilled voucher (null otherwise).
    dispute_until: datetime | None


class PurchaseResult(PurchaseOut):
    """``POST /rewards/{id}/purchase``: the new voucher plus my wallet balance after it."""

    balance: int
