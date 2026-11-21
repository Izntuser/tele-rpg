"""quest offer flow: revision decline reason, one pending revision per template, quest indexes

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("quest_revision", sa.Column("decline_reason", sa.Text(), nullable=True))
    op.create_index(
        "ux_quest_revision_one_pending",
        "quest_revision",
        ["template_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_quest_occurrence_assignee_id_status", "quest_occurrence", ["assignee_id", "status"]
    )
    op.create_index("ix_quest_template_partnership_id", "quest_template", ["partnership_id"])


def downgrade() -> None:
    op.drop_index("ix_quest_template_partnership_id", table_name="quest_template")
    op.drop_index("ix_quest_occurrence_assignee_id_status", table_name="quest_occurrence")
    op.drop_index("ux_quest_revision_one_pending", table_name="quest_revision")
    op.drop_column("quest_revision", "decline_reason")
