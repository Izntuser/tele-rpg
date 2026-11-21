from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at, id_pk, pg_enum
from app.modules.common.enums import GoldTransactionType


class Wallet(Base):
    """Gold wallet per (user, partnership). ``balance`` is a cache; the ledger is the truth:
    services keep ``balance == sum(gold_transaction.amount)`` in the same transaction."""

    __tablename__ = "wallet"
    __table_args__ = (
        CheckConstraint("balance >= 0", name="balance_non_negative"),
        UniqueConstraint("user_id", "partnership_id"),
        # Target of gold_transaction's composite FK: a ledger row's owner is its wallet's (0004).
        UniqueConstraint("id", "user_id", "partnership_id"),
    )

    id: Mapped[int] = id_pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    partnership_id: Mapped[int] = mapped_column(ForeignKey("partnership.id"))
    balance: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class GoldTransaction(Base):
    """Append-only Gold ledger row. ``amount`` is signed; its sign must match ``type``."""

    __tablename__ = "gold_transaction"
    __table_args__ = (
        CheckConstraint(
            "(type = 'quest_reward' AND amount >= 0)"
            " OR (type = 'reward_purchase' AND amount < 0)"
            " OR (type = 'reward_refund' AND amount > 0)"
            " OR type = 'adjustment'",
            name="amount_sign_matches_type",
        ),
        # A quest reward names its occurrence; a purchase or refund names its purchase (0004).
        CheckConstraint(
            "(type <> 'quest_reward' OR quest_occurrence_id IS NOT NULL)"
            " AND (type NOT IN ('reward_purchase', 'reward_refund') OR purchase_id IS NOT NULL)",
            name="reference_matches_type",
        ),
        # user_id / partnership_id must be the wallet's own (0004).
        ForeignKeyConstraint(
            ["wallet_id", "user_id", "partnership_id"],
            ["wallet.id", "wallet.user_id", "wallet.partnership_id"],
            name="fk_gold_transaction_wallet_owner",
        ),
        Index(None, "wallet_id"),
        # GET /economy/transactions: my ledger, newest first, keyset on id.
        Index(None, "user_id", "id"),
    )

    id: Mapped[int] = id_pk()
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallet.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    partnership_id: Mapped[int] = mapped_column(ForeignKey("partnership.id"))
    type: Mapped[GoldTransactionType] = mapped_column(pg_enum(GoldTransactionType))
    amount: Mapped[int] = mapped_column(Integer)
    quest_occurrence_id: Mapped[int | None] = mapped_column(ForeignKey("quest_occurrence.id"))
    purchase_id: Mapped[int | None] = mapped_column(ForeignKey("reward_purchase.id"))
    # quest:{occurrence_id}, purchase:{user_id}:{key}, refund:{purchase_id} (economy.service)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = created_at()
