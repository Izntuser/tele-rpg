"""initial schema: every table, enum, constraint and index from ARCHITECTURE §4

Revision ID: 0001
Revises:
Create Date: 2026-11-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENUMS: dict[str, postgresql.ENUM] = {
    "locale": postgresql.ENUM("en", "uk", name="locale", create_type=False),
    "attribute": postgresql.ENUM(
        "physical",
        "intellectual",
        "discipline",
        "social",
        "creativity",
        "wellbeing",
        name="attribute",
        create_type=False,
    ),
    "goal_status": postgresql.ENUM("active", "archived", name="goal_status", create_type=False),
    "notification_category": postgresql.ENUM(
        "quests",
        "reviews",
        "rewards",
        "reminders",
        "summary",
        name="notification_category",
        create_type=False,
    ),
    "notification_status": postgresql.ENUM(
        "pending", "sent", "skipped", "failed", name="notification_status", create_type=False
    ),
    "partnership_status": postgresql.ENUM(
        "active", "ended", name="partnership_status", create_type=False
    ),
    "invitation_status": postgresql.ENUM(
        "pending", "accepted", "revoked", "expired", name="invitation_status", create_type=False
    ),
    "difficulty": postgresql.ENUM(
        "easy", "normal", "hard", "epic", name="difficulty", create_type=False
    ),
    "recurrence": postgresql.ENUM("once", "daily", "weekly", name="recurrence", create_type=False),
    "confirmation_mode": postgresql.ENUM(
        "manual", "auto", name="confirmation_mode", create_type=False
    ),
    "file_kind": postgresql.ENUM(
        "avatar", "quest_photo", "reward_image", name="file_kind", create_type=False
    ),
    "journal_visibility": postgresql.ENUM(
        "private", "shared", name="journal_visibility", create_type=False
    ),
    "quest_template_status": postgresql.ENUM(
        "offered",
        "active",
        "paused",
        "declined",
        "cancelled",
        "completed",
        name="quest_template_status",
        create_type=False,
    ),
    "quest_occurrence_status": postgresql.ENUM(
        "offered",
        "active",
        "in_review",
        "completed",
        "declined",
        "expired",
        "cancelled",
        name="quest_occurrence_status",
        create_type=False,
    ),
    "quest_revision_status": postgresql.ENUM(
        "pending",
        "accepted",
        "declined",
        "superseded",
        name="quest_revision_status",
        create_type=False,
    ),
    "reward_status": postgresql.ENUM(
        "active", "hidden", "sold_out", name="reward_status", create_type=False
    ),
    "submission_review_status": postgresql.ENUM(
        "pending", "approved", "redo", name="submission_review_status", create_type=False
    ),
    "reward_purchase_status": postgresql.ENUM(
        "purchased",
        "requested",
        "scheduled",
        "fulfilled",
        "cancelled",
        "refunded",
        name="reward_purchase_status",
        create_type=False,
    ),
    "wishlist_status": postgresql.ENUM(
        "open", "offered", "archived", name="wishlist_status", create_type=False
    ),
    "gold_transaction_type": postgresql.ENUM(
        "quest_reward",
        "reward_purchase",
        "reward_refund",
        "adjustment",
        name="gold_transaction_type",
        create_type=False,
    ),
}

# Foreign keys that close a reference cycle (or point at a later table); added after all tables.
_DEFERRED_FKS: list[tuple[str, str, str, str]] = [
    ("fk_user_avatar_file_id_file", "user", "avatar_file_id", "file"),
    (
        "fk_quest_template_current_revision_id_quest_revision",
        "quest_template",
        "current_revision_id",
        "quest_revision",
    ),
    (
        "fk_reward_source_wishlist_item_id_wishlist_item",
        "reward",
        "source_wishlist_item_id",
        "wishlist_item",
    ),
]

# The partial unique indexes ux_partnership_active_user_{a,b} only catch a user appearing twice
# in the *same* column. This trigger also rejects a user who is user_a in one active
# partnership and user_b in another. A transaction-scoped advisory lock per user serializes
# concurrent activations, and under READ COMMITTED the EXISTS query then sees rows the other
# transaction committed. Raises unique_violation (23505) like the indexes do.
_ONE_ACTIVE_FUNCTION = """
CREATE FUNCTION partnership_one_active_per_user() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status <> 'active' THEN
        RETURN NEW;
    END IF;
    PERFORM pg_advisory_xact_lock(
        hashtextextended('partnership_active_user:' || LEAST(NEW.user_a_id, NEW.user_b_id), 0));
    PERFORM pg_advisory_xact_lock(
        hashtextextended('partnership_active_user:' || GREATEST(NEW.user_a_id, NEW.user_b_id), 0));
    IF EXISTS (
        SELECT 1 FROM partnership p
        WHERE p.status = 'active'
          AND p.id <> NEW.id
          AND (p.user_a_id IN (NEW.user_a_id, NEW.user_b_id)
               OR p.user_b_id IN (NEW.user_a_id, NEW.user_b_id))
    ) THEN
        RAISE EXCEPTION 'user already has an active partnership'
            USING ERRCODE = 'unique_violation',
                  CONSTRAINT = 'partnership_one_active_per_user',
                  TABLE = 'partnership';
    END IF;
    RETURN NEW;
END
$$
"""

_ONE_ACTIVE_TRIGGER = """
CREATE TRIGGER partnership_one_active_per_user
BEFORE INSERT OR UPDATE OF status, user_a_id, user_b_id ON partnership
FOR EACH ROW EXECUTE FUNCTION partnership_one_active_per_user()
"""


def upgrade() -> None:
    bind = op.get_bind()
    for enum in _ENUMS.values():
        enum.create(bind, checkfirst=False)

    op.create_table(
        "user",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column("tg_username", sa.String(length=64), nullable=True),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("avatar_file_id", sa.BigInteger(), nullable=True),
        sa.Column("locale", _ENUMS["locale"], server_default="en", nullable=False),
        sa.Column("timezone", sa.String(length=64), server_default="UTC", nullable=False),
        sa.Column("can_message", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "notification_prefs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("onboarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user")),
        sa.UniqueConstraint("tg_user_id", name=op.f("uq_user_tg_user_id")),
    )
    op.create_table(
        "achievement_unlock",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column(
            "unlocked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name=op.f("fk_achievement_unlock_user_id_user")
        ),
        sa.PrimaryKeyConstraint("user_id", "code", name=op.f("pk_achievement_unlock")),
    )
    op.create_table(
        "character",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("nickname", sa.String(length=64), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("total_xp", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("total_xp >= 0", name=op.f("ck_character_total_xp_non_negative")),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name=op.f("fk_character_user_id_user")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_character")),
        sa.UniqueConstraint("user_id", name=op.f("uq_character_user_id")),
    )
    op.create_table(
        "development_goal",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("attribute", _ENUMS["attribute"], nullable=True),
        sa.Column("status", _ENUMS["goal_status"], server_default="active", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name=op.f("fk_development_goal_user_id_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_development_goal")),
    )
    op.create_table(
        "idempotency_key",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("endpoint", sa.String(length=255), nullable=False),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name=op.f("fk_idempotency_key_user_id_user")
        ),
        sa.PrimaryKeyConstraint("user_id", "key", name=op.f("pk_idempotency_key")),
    )
    op.create_table(
        "life_balance_target",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("attribute", _ENUMS["attribute"], nullable=False),
        sa.Column("weekly_xp_target", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.CheckConstraint(
            "weekly_xp_target >= 0",
            name=op.f("ck_life_balance_target_weekly_xp_target_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name=op.f("fk_life_balance_target_user_id_user")
        ),
        sa.PrimaryKeyConstraint("user_id", "attribute", name=op.f("pk_life_balance_target")),
    )
    op.create_table(
        "notification",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("recipient_id", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("category", _ENUMS["notification_category"], nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=True),
        sa.Column("entity_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("deep_link", sa.String(length=512), nullable=True),
        sa.Column(
            "status", _ENUMS["notification_status"], server_default="pending", nullable=False
        ),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "send_after",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_notification_attempts_non_negative")),
        sa.ForeignKeyConstraint(
            ["recipient_id"], ["user.id"], name=op.f("fk_notification_recipient_id_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification")),
    )
    op.create_index(
        "ux_notification_dedupe",
        "notification",
        [
            "recipient_id",
            "type",
            "entity_id",
            sa.literal_column("((send_after AT TIME ZONE 'UTC')::date)"),
        ],
        unique=True,
        postgresql_where=sa.text("category IN ('reminders', 'summary')"),
        postgresql_nulls_not_distinct=True,
    )
    op.create_table(
        "partnership",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_a_id", sa.BigInteger(), nullable=False),
        sa.Column("user_b_id", sa.BigInteger(), nullable=False),
        sa.Column("status", _ENUMS["partnership_status"], server_default="active", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_by", sa.BigInteger(), nullable=True),
        sa.CheckConstraint("user_a_id < user_b_id", name=op.f("ck_partnership_users_ordered")),
        sa.ForeignKeyConstraint(
            ["ended_by"], ["user.id"], name=op.f("fk_partnership_ended_by_user")
        ),
        sa.ForeignKeyConstraint(
            ["user_a_id"], ["user.id"], name=op.f("fk_partnership_user_a_id_user")
        ),
        sa.ForeignKeyConstraint(
            ["user_b_id"], ["user.id"], name=op.f("fk_partnership_user_b_id_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_partnership")),
        sa.UniqueConstraint(
            "user_a_id", "user_b_id", name=op.f("uq_partnership_user_a_id_user_b_id")
        ),
    )
    op.create_index(
        "ux_partnership_active_user_a",
        "partnership",
        ["user_a_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ux_partnership_active_user_b",
        "partnership",
        ["user_b_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "partnership_invitation",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("creator_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("status", _ENUMS["invitation_status"], server_default="pending", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_by", sa.BigInteger(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["accepted_by"], ["user.id"], name=op.f("fk_partnership_invitation_accepted_by_user")
        ),
        sa.ForeignKeyConstraint(
            ["creator_id"], ["user.id"], name=op.f("fk_partnership_invitation_creator_id_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_partnership_invitation")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_partnership_invitation_token_hash")),
    )
    op.create_index(
        "ux_partnership_invitation_pending_creator",
        "partnership_invitation",
        ["creator_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_table(
        "saved_quest_template",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("attribute", _ENUMS["attribute"], nullable=False),
        sa.Column("difficulty", _ENUMS["difficulty"], nullable=False),
        sa.Column("gold", sa.Integer(), nullable=False),
        sa.Column("recurrence", _ENUMS["recurrence"], nullable=False),
        sa.Column(
            "confirmation", _ENUMS["confirmation_mode"], server_default="manual", nullable=False
        ),
        sa.Column("photo_required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.CheckConstraint(
            "gold >= 0 AND gold <= 1000", name=op.f("ck_saved_quest_template_gold_range")
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["user.id"], name=op.f("fk_saved_quest_template_owner_id_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_quest_template")),
    )
    op.create_table(
        "character_attribute",
        sa.Column("character_id", sa.BigInteger(), nullable=False),
        sa.Column("attribute", _ENUMS["attribute"], nullable=False),
        sa.Column("xp", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint("xp >= 0", name=op.f("ck_character_attribute_xp_non_negative")),
        sa.ForeignKeyConstraint(
            ["character_id"],
            ["character.id"],
            name=op.f("fk_character_attribute_character_id_character"),
        ),
        sa.PrimaryKeyConstraint("character_id", "attribute", name=op.f("pk_character_attribute")),
    )
    op.create_table(
        "file",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("partnership_id", sa.BigInteger(), nullable=True),
        sa.Column("kind", _ENUMS["file_kind"], nullable=False),
        sa.Column("storage_key", sa.String(length=255), nullable=False),
        sa.Column("mime", sa.String(length=64), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("size >= 0", name=op.f("ck_file_size_non_negative")),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], name=op.f("fk_file_owner_id_user")),
        sa.ForeignKeyConstraint(
            ["partnership_id"], ["partnership.id"], name=op.f("fk_file_partnership_id_partnership")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_file")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_file_storage_key")),
    )
    op.create_table(
        "journal_event",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("partnership_id", sa.BigInteger(), nullable=True),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("visibility", _ENUMS["journal_visibility"], nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=True),
        sa.Column("entity_id", sa.BigInteger(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["partnership_id"],
            ["partnership.id"],
            name=op.f("fk_journal_event_partnership_id_partnership"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name=op.f("fk_journal_event_user_id_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_journal_event")),
    )
    op.create_index(
        op.f("ix_journal_event_partnership_id_created_at"),
        "journal_event",
        ["partnership_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "quest_template",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("partnership_id", sa.BigInteger(), nullable=False),
        sa.Column("creator_id", sa.BigInteger(), nullable=False),
        sa.Column("assignee_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("attribute", _ENUMS["attribute"], nullable=False),
        sa.Column("difficulty", _ENUMS["difficulty"], nullable=False),
        sa.Column("gold", sa.Integer(), nullable=False),
        sa.Column("recurrence", _ENUMS["recurrence"], nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "confirmation", _ENUMS["confirmation_mode"], server_default="manual", nullable=False
        ),
        sa.Column("photo_required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "status", _ENUMS["quest_template_status"], server_default="offered", nullable=False
        ),
        sa.Column("current_revision_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "deadline_at IS NULL OR recurrence = 'once'",
            name=op.f("ck_quest_template_deadline_only_for_once"),
        ),
        sa.CheckConstraint(
            "assignee_id <> creator_id", name=op.f("ck_quest_template_assignee_not_creator")
        ),
        sa.CheckConstraint("gold >= 0 AND gold <= 1000", name=op.f("ck_quest_template_gold_range")),
        sa.ForeignKeyConstraint(
            ["assignee_id"], ["user.id"], name=op.f("fk_quest_template_assignee_id_user")
        ),
        sa.ForeignKeyConstraint(
            ["creator_id"], ["user.id"], name=op.f("fk_quest_template_creator_id_user")
        ),
        sa.ForeignKeyConstraint(
            ["partnership_id"],
            ["partnership.id"],
            name=op.f("fk_quest_template_partnership_id_partnership"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quest_template")),
    )
    op.create_table(
        "wallet",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("partnership_id", sa.BigInteger(), nullable=False),
        sa.Column("balance", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint("balance >= 0", name=op.f("ck_wallet_balance_non_negative")),
        sa.ForeignKeyConstraint(
            ["partnership_id"],
            ["partnership.id"],
            name=op.f("fk_wallet_partnership_id_partnership"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name=op.f("fk_wallet_user_id_user")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wallet")),
        sa.UniqueConstraint(
            "user_id", "partnership_id", name=op.f("uq_wallet_user_id_partnership_id")
        ),
    )
    op.create_table(
        "quest_occurrence",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("template_id", sa.BigInteger(), nullable=False),
        sa.Column("assignee_id", sa.BigInteger(), nullable=False),
        sa.Column("status", _ENUMS["quest_occurrence_status"], nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terms_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", sa.BigInteger(), nullable=True),
        sa.Column("decline_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["assignee_id"], ["user.id"], name=op.f("fk_quest_occurrence_assignee_id_user")
        ),
        sa.ForeignKeyConstraint(
            ["cancelled_by"], ["user.id"], name=op.f("fk_quest_occurrence_cancelled_by_user")
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["quest_template.id"],
            name=op.f("fk_quest_occurrence_template_id_quest_template"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quest_occurrence")),
        sa.UniqueConstraint(
            "template_id",
            "scheduled_date",
            name=op.f("uq_quest_occurrence_template_id_scheduled_date"),
        ),
    )
    op.create_table(
        "quest_revision",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("template_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("terms", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status", _ENUMS["quest_revision_status"], server_default="pending", nullable=False
        ),
        sa.Column("proposed_by", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("version >= 1", name=op.f("ck_quest_revision_version_positive")),
        sa.ForeignKeyConstraint(
            ["proposed_by"], ["user.id"], name=op.f("fk_quest_revision_proposed_by_user")
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["quest_template.id"],
            name=op.f("fk_quest_revision_template_id_quest_template"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quest_revision")),
        sa.UniqueConstraint(
            "template_id", "version", name=op.f("uq_quest_revision_template_id_version")
        ),
    )
    op.create_table(
        "quest_streak",
        sa.Column("template_id", sa.BigInteger(), nullable=False),
        sa.Column("current", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("best", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_completed_date", sa.Date(), nullable=True),
        sa.CheckConstraint("best >= current", name=op.f("ck_quest_streak_best_at_least_current")),
        sa.CheckConstraint("current >= 0", name=op.f("ck_quest_streak_current_non_negative")),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["quest_template.id"],
            name=op.f("fk_quest_streak_template_id_quest_template"),
        ),
        sa.PrimaryKeyConstraint("template_id", name=op.f("pk_quest_streak")),
    )
    op.create_table(
        "reward",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("partnership_id", sa.BigInteger(), nullable=False),
        sa.Column("creator_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("image_file_id", sa.BigInteger(), nullable=True),
        sa.Column("quantity_limit", sa.Integer(), nullable=True),
        sa.Column("quantity_remaining", sa.Integer(), nullable=True),
        sa.Column("cooldown_days", sa.Integer(), nullable=True),
        sa.Column("status", _ENUMS["reward_status"], server_default="active", nullable=False),
        sa.Column("source_wishlist_item_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("cooldown_days >= 0", name=op.f("ck_reward_cooldown_days_non_negative")),
        sa.CheckConstraint("price > 0", name=op.f("ck_reward_price_positive")),
        sa.CheckConstraint("quantity_limit > 0", name=op.f("ck_reward_quantity_limit_positive")),
        sa.CheckConstraint(
            "quantity_remaining >= 0", name=op.f("ck_reward_quantity_remaining_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["creator_id"], ["user.id"], name=op.f("fk_reward_creator_id_user")
        ),
        sa.ForeignKeyConstraint(
            ["image_file_id"], ["file.id"], name=op.f("fk_reward_image_file_id_file")
        ),
        sa.ForeignKeyConstraint(
            ["partnership_id"],
            ["partnership.id"],
            name=op.f("fk_reward_partnership_id_partnership"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reward")),
    )
    op.create_table(
        "quest_submission",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("occurrence_id", sa.BigInteger(), nullable=False),
        sa.Column("submitted_by", sa.BigInteger(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("attachment_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "review_status",
            _ENUMS["submission_review_status"],
            server_default="pending",
            nullable=False,
        ),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "review_status <> 'redo'"
            " OR (review_comment IS NOT NULL AND btrim(review_comment) <> '')",
            name=op.f("ck_quest_submission_redo_requires_comment"),
        ),
        sa.ForeignKeyConstraint(
            ["attachment_id"], ["file.id"], name=op.f("fk_quest_submission_attachment_id_file")
        ),
        sa.ForeignKeyConstraint(
            ["occurrence_id"],
            ["quest_occurrence.id"],
            name=op.f("fk_quest_submission_occurrence_id_quest_occurrence"),
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"], ["user.id"], name=op.f("fk_quest_submission_submitted_by_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quest_submission")),
    )
    op.create_table(
        "reward_purchase",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("reward_id", sa.BigInteger(), nullable=False),
        sa.Column("partnership_id", sa.BigInteger(), nullable=False),
        sa.Column("buyer_id", sa.BigInteger(), nullable=False),
        sa.Column("provider_id", sa.BigInteger(), nullable=False),
        sa.Column("price_paid", sa.Integer(), nullable=False),
        sa.Column("reward_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status", _ENUMS["reward_purchase_status"], server_default="purchased", nullable=False
        ),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("schedule_note", sa.Text(), nullable=True),
        sa.Column(
            "purchased_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disputed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_by", sa.BigInteger(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.CheckConstraint(
            "buyer_id <> provider_id", name=op.f("ck_reward_purchase_buyer_not_provider")
        ),
        sa.CheckConstraint("price_paid > 0", name=op.f("ck_reward_purchase_price_paid_positive")),
        sa.ForeignKeyConstraint(
            ["buyer_id"], ["user.id"], name=op.f("fk_reward_purchase_buyer_id_user")
        ),
        sa.ForeignKeyConstraint(
            ["partnership_id"],
            ["partnership.id"],
            name=op.f("fk_reward_purchase_partnership_id_partnership"),
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["user.id"], name=op.f("fk_reward_purchase_provider_id_user")
        ),
        sa.ForeignKeyConstraint(
            ["refunded_by"], ["user.id"], name=op.f("fk_reward_purchase_refunded_by_user")
        ),
        sa.ForeignKeyConstraint(
            ["reward_id"], ["reward.id"], name=op.f("fk_reward_purchase_reward_id_reward")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reward_purchase")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_reward_purchase_idempotency_key")),
    )
    op.create_table(
        "wishlist_item",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", _ENUMS["wishlist_status"], server_default="open", nullable=False),
        sa.Column("linked_reward_id", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["linked_reward_id"],
            ["reward.id"],
            name=op.f("fk_wishlist_item_linked_reward_id_reward"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name=op.f("fk_wishlist_item_user_id_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wishlist_item")),
    )
    op.create_table(
        "xp_transaction",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("quest_occurrence_id", sa.BigInteger(), nullable=False),
        sa.Column("xp", sa.Integer(), nullable=False),
        sa.Column("attribute", _ENUMS["attribute"], nullable=False),
        sa.Column("attribute_xp", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attribute_xp >= 0", name=op.f("ck_xp_transaction_attribute_xp_non_negative")
        ),
        sa.CheckConstraint("xp >= 0", name=op.f("ck_xp_transaction_xp_non_negative")),
        sa.ForeignKeyConstraint(
            ["quest_occurrence_id"],
            ["quest_occurrence.id"],
            name=op.f("fk_xp_transaction_quest_occurrence_id_quest_occurrence"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name=op.f("fk_xp_transaction_user_id_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_xp_transaction")),
        sa.UniqueConstraint(
            "quest_occurrence_id", name=op.f("uq_xp_transaction_quest_occurrence_id")
        ),
    )
    op.create_table(
        "gold_transaction",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("wallet_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("partnership_id", sa.BigInteger(), nullable=False),
        sa.Column("type", _ENUMS["gold_transaction_type"], nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("quest_occurrence_id", sa.BigInteger(), nullable=True),
        sa.Column("purchase_id", sa.BigInteger(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(type = 'quest_reward' AND amount >= 0)"
            " OR (type = 'reward_purchase' AND amount < 0)"
            " OR (type = 'reward_refund' AND amount > 0)"
            " OR type = 'adjustment'",
            name=op.f("ck_gold_transaction_amount_sign_matches_type"),
        ),
        sa.ForeignKeyConstraint(
            ["partnership_id"],
            ["partnership.id"],
            name=op.f("fk_gold_transaction_partnership_id_partnership"),
        ),
        sa.ForeignKeyConstraint(
            ["purchase_id"],
            ["reward_purchase.id"],
            name=op.f("fk_gold_transaction_purchase_id_reward_purchase"),
        ),
        sa.ForeignKeyConstraint(
            ["quest_occurrence_id"],
            ["quest_occurrence.id"],
            name=op.f("fk_gold_transaction_quest_occurrence_id_quest_occurrence"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name=op.f("fk_gold_transaction_user_id_user")
        ),
        sa.ForeignKeyConstraint(
            ["wallet_id"], ["wallet.id"], name=op.f("fk_gold_transaction_wallet_id_wallet")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gold_transaction")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_gold_transaction_idempotency_key")),
    )

    for name, source, column, referent in _DEFERRED_FKS:
        op.create_foreign_key(name, source, referent, [column], ["id"])

    op.execute(_ONE_ACTIVE_FUNCTION)
    op.execute(_ONE_ACTIVE_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER partnership_one_active_per_user ON partnership")
    op.execute("DROP FUNCTION partnership_one_active_per_user()")
    for name, source, _column, _referent in reversed(_DEFERRED_FKS):
        op.drop_constraint(name, source, type_="foreignkey")

    op.drop_table("gold_transaction")
    op.drop_table("xp_transaction")
    op.drop_table("wishlist_item")
    op.drop_table("reward_purchase")
    op.drop_table("quest_submission")
    op.drop_table("reward")
    op.drop_table("quest_streak")
    op.drop_table("quest_revision")
    op.drop_table("quest_occurrence")
    op.drop_table("wallet")
    op.drop_table("quest_template")
    op.drop_index(op.f("ix_journal_event_partnership_id_created_at"), table_name="journal_event")
    op.drop_table("journal_event")
    op.drop_table("file")
    op.drop_table("character_attribute")
    op.drop_table("saved_quest_template")
    op.drop_index(
        "ux_partnership_invitation_pending_creator",
        table_name="partnership_invitation",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_table("partnership_invitation")
    op.drop_index(
        "ux_partnership_active_user_b",
        table_name="partnership",
        postgresql_where=sa.text("status = 'active'"),
    )
    op.drop_index(
        "ux_partnership_active_user_a",
        table_name="partnership",
        postgresql_where=sa.text("status = 'active'"),
    )
    op.drop_table("partnership")
    op.drop_index(
        "ux_notification_dedupe",
        table_name="notification",
        postgresql_where=sa.text("category IN ('reminders', 'summary')"),
        postgresql_nulls_not_distinct=True,
    )
    op.drop_table("notification")
    op.drop_table("life_balance_target")
    op.drop_table("idempotency_key")
    op.drop_table("development_goal")
    op.drop_table("character")
    op.drop_table("achievement_unlock")
    op.drop_table("user")

    bind = op.get_bind()
    for enum in reversed(list(_ENUMS.values())):
        enum.drop(bind, checkfirst=False)
