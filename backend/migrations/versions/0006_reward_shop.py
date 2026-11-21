"""reward shop: purchase/reward partnership FK and shop/inventory indexes

``reward_purchase(reward_id, partnership_id)`` must match its reward's own partnership
(composite FK onto a new ``reward(id, partnership_id)`` unique constraint). Indexes serve the
shop list (``reward(partnership_id, creator_id)``), the purchase cooldown check
(``reward_purchase(reward_id, buyer_id)``) and the inventory lists by side.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        op.f("uq_reward_id_partnership_id"), "reward", ["id", "partnership_id"]
    )
    op.create_foreign_key(
        op.f("fk_reward_purchase_reward_partnership"),
        "reward_purchase",
        "reward",
        ["reward_id", "partnership_id"],
        ["id", "partnership_id"],
    )
    op.create_index(
        op.f("ix_reward_partnership_id_creator_id"), "reward", ["partnership_id", "creator_id"]
    )
    op.create_index(
        op.f("ix_reward_purchase_reward_id_buyer_id"), "reward_purchase", ["reward_id", "buyer_id"]
    )
    op.create_index(op.f("ix_reward_purchase_buyer_id_id"), "reward_purchase", ["buyer_id", "id"])
    op.create_index(
        op.f("ix_reward_purchase_provider_id_id"), "reward_purchase", ["provider_id", "id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_reward_purchase_provider_id_id"), table_name="reward_purchase")
    op.drop_index(op.f("ix_reward_purchase_buyer_id_id"), table_name="reward_purchase")
    op.drop_index(op.f("ix_reward_purchase_reward_id_buyer_id"), table_name="reward_purchase")
    op.drop_index(op.f("ix_reward_partnership_id_creator_id"), table_name="reward")
    op.drop_constraint(
        op.f("fk_reward_purchase_reward_partnership"), "reward_purchase", type_="foreignkey"
    )
    op.drop_constraint(op.f("uq_reward_id_partnership_id"), "reward", type_="unique")
