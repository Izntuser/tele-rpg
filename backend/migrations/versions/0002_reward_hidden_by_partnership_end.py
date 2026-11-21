"""reward.hidden_by_partnership_end: marks rewards hidden by ending a partnership

Re-pairing restores only these, so rewards their creator hid on purpose stay hidden.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "reward",
        sa.Column(
            "hidden_by_partnership_end",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("reward", "hidden_by_partnership_end")
