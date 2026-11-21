from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at, id_pk, pg_enum
from app.modules.common.enums import RewardPurchaseStatus, RewardStatus


class Reward(Base):
    __tablename__ = "reward"
    __table_args__ = (
        CheckConstraint("price > 0", name="price_positive"),
        CheckConstraint("quantity_remaining >= 0", name="quantity_remaining_non_negative"),
        CheckConstraint("quantity_limit > 0", name="quantity_limit_positive"),
        CheckConstraint(
            "quantity_remaining <= quantity_limit", name="quantity_remaining_within_limit"
        ),
        CheckConstraint("cooldown_days >= 0", name="cooldown_days_non_negative"),
        # Target of reward_purchase's composite FK: a purchase's partnership is its reward's (0006).
        UniqueConstraint("id", "partnership_id"),
        # GET /rewards: a shop is (partnership, creator) (0006).
        Index(None, "partnership_id", "creator_id"),
    )

    id: Mapped[int] = id_pk()
    partnership_id: Mapped[int] = mapped_column(ForeignKey("partnership.id"))
    creator_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    price: Mapped[int] = mapped_column(Integer)
    image_file_id: Mapped[int | None] = mapped_column(ForeignKey("file.id"))
    quantity_limit: Mapped[int | None] = mapped_column(Integer)
    quantity_remaining: Mapped[int | None] = mapped_column(Integer)
    cooldown_days: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[RewardStatus] = mapped_column(
        pg_enum(RewardStatus), server_default=RewardStatus.ACTIVE.value
    )
    # Set only by ending the partnership (it hid this reward); re-pairing restores exactly
    # these and clears it. A reward its creator hid on purpose never carries it.
    hidden_by_partnership_end: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    # Circular with wishlist_item.linked_reward_id, hence created by ALTER after both tables.
    source_wishlist_item_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "wishlist_item.id",
            use_alter=True,
            name="fk_reward_source_wishlist_item_id_wishlist_item",
        )
    )
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class RewardPurchase(Base):
    """A purchased reward; doubles as the buyer's inventory item (voucher)."""

    __tablename__ = "reward_purchase"
    __table_args__ = (
        CheckConstraint("price_paid > 0", name="price_paid_positive"),
        CheckConstraint("buyer_id <> provider_id", name="buyer_not_provider"),
        # partnership_id must be the reward's own (0006).
        ForeignKeyConstraint(
            ["reward_id", "partnership_id"],
            ["reward.id", "reward.partnership_id"],
            name="fk_reward_purchase_reward_partnership",
        ),
        # Cooldown check (last purchase of a reward by a buyer) and GET /inventory (0006).
        Index(None, "reward_id", "buyer_id"),
        Index(None, "buyer_id", "id"),
        Index(None, "provider_id", "id"),
    )

    id: Mapped[int] = id_pk()
    reward_id: Mapped[int] = mapped_column(ForeignKey("reward.id"))
    partnership_id: Mapped[int] = mapped_column(ForeignKey("partnership.id"))
    buyer_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    provider_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    price_paid: Mapped[int] = mapped_column(Integer)
    reward_snapshot: Mapped[dict[str, Any]]
    status: Mapped[RewardPurchaseStatus] = mapped_column(
        pg_enum(RewardPurchaseStatus), server_default=RewardPurchaseStatus.PURCHASED.value
    )
    scheduled_for: Mapped[datetime | None]
    schedule_note: Mapped[str | None] = mapped_column(Text)
    purchased_at: Mapped[datetime] = mapped_column(server_default=func.now())
    requested_at: Mapped[datetime | None]
    scheduled_at: Mapped[datetime | None]
    fulfilled_at: Mapped[datetime | None]
    disputed_at: Mapped[datetime | None]
    refunded_at: Mapped[datetime | None]
    refunded_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True)
