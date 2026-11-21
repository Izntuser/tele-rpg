"""user.tg_user_id: partial unique index instead of a unique constraint

Postgres counts only non-partial unique indexes as row keys. With the full unique constraint,
account deletion's ``tg_user_id = -id`` rewrite was a key update (an implicit ``FOR UPDATE`` on
the user row) that conflicts with the ``FOR KEY SHARE`` taken by FK checks of concurrent quest
writes. Live Telegram ids are positive and deleted rows hold ``-id``, so uniqueness over
``tg_user_id > 0`` keeps the same guarantee. A plain index keeps lookups by Telegram id fast.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ux_user_tg_user_id_live",
        "user",
        ["tg_user_id"],
        unique=True,
        postgresql_where=sa.text("tg_user_id > 0"),
    )
    op.create_index(op.f("ix_user_tg_user_id"), "user", ["tg_user_id"])
    op.drop_constraint(op.f("uq_user_tg_user_id"), "user", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint(op.f("uq_user_tg_user_id"), "user", ["tg_user_id"])
    op.drop_index(op.f("ix_user_tg_user_id"), table_name="user")
    op.drop_index(
        "ux_user_tg_user_id_live",
        table_name="user",
        postgresql_where=sa.text("tg_user_id > 0"),
    )
