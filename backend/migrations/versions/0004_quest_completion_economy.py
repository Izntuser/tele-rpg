"""quest completion and economy: ledger reference checks, wallet-owner FK, ledger indexes

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        op.f("uq_wallet_id_user_id_partnership_id"), "wallet", ["id", "user_id", "partnership_id"]
    )
    op.create_foreign_key(
        op.f("fk_gold_transaction_wallet_owner"),
        "gold_transaction",
        "wallet",
        ["wallet_id", "user_id", "partnership_id"],
        ["id", "user_id", "partnership_id"],
    )
    op.create_check_constraint(
        op.f("ck_gold_transaction_reference_matches_type"),
        "gold_transaction",
        "(type <> 'quest_reward' OR quest_occurrence_id IS NOT NULL)"
        " AND (type NOT IN ('reward_purchase', 'reward_refund') OR purchase_id IS NOT NULL)",
    )
    op.create_index(op.f("ix_gold_transaction_wallet_id"), "gold_transaction", ["wallet_id"])
    op.create_index(op.f("ix_gold_transaction_user_id_id"), "gold_transaction", ["user_id", "id"])
    op.create_index(op.f("ix_xp_transaction_user_id"), "xp_transaction", ["user_id"])
    op.create_index(op.f("ix_idempotency_key_created_at"), "idempotency_key", ["created_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_idempotency_key_created_at"), table_name="idempotency_key")
    op.drop_index(op.f("ix_xp_transaction_user_id"), table_name="xp_transaction")
    op.drop_index(op.f("ix_gold_transaction_user_id_id"), table_name="gold_transaction")
    op.drop_index(op.f("ix_gold_transaction_wallet_id"), table_name="gold_transaction")
    op.drop_constraint(
        op.f("ck_gold_transaction_reference_matches_type"), "gold_transaction", type_="check"
    )
    op.drop_constraint(
        op.f("fk_gold_transaction_wallet_owner"), "gold_transaction", type_="foreignkey"
    )
    op.drop_constraint(op.f("uq_wallet_id_user_id_partnership_id"), "wallet", type_="unique")
