"""Migration 0001 builds exactly the ARCHITECTURE §4 schema, round-trips, and has no drift.

These tests are sync on purpose: alembic's env.py runs its own event loop. Each one leaves the
test database at head.
"""

import asyncio
from collections.abc import Coroutine
from typing import Any

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Enum, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.db.base import Base, pg_type_name
from app.modules.common.enums import ALL_ENUMS
from tests.conftest import TEST_DATABASE_URL, alembic_config

EXPECTED_TABLES = {
    "user",
    "character",
    "character_attribute",
    "partnership",
    "partnership_invitation",
    "wallet",
    "gold_transaction",
    "xp_transaction",
    "quest_template",
    "quest_revision",
    "quest_occurrence",
    "quest_submission",
    "quest_streak",
    "saved_quest_template",
    "reward",
    "reward_purchase",
    "journal_event",
    "achievement_unlock",
    "development_goal",
    "wishlist_item",
    "life_balance_target",
    "notification",
    "file",
    "idempotency_key",
}

EXPECTED_CHECKS = {
    "ck_character_total_xp_non_negative",
    "ck_character_attribute_xp_non_negative",
    "ck_partnership_users_ordered",
    "ck_wallet_balance_non_negative",
    "ck_gold_transaction_amount_sign_matches_type",
    "ck_xp_transaction_xp_non_negative",
    "ck_xp_transaction_attribute_xp_non_negative",
    "ck_quest_template_assignee_not_creator",
    "ck_quest_template_gold_range",
    "ck_quest_template_deadline_only_for_once",
    "ck_quest_revision_version_positive",
    "ck_quest_submission_redo_requires_comment",
    "ck_quest_streak_current_non_negative",
    "ck_quest_streak_best_at_least_current",
    "ck_saved_quest_template_gold_range",
    "ck_reward_price_positive",
    "ck_reward_quantity_remaining_non_negative",
    "ck_reward_quantity_limit_positive",
    "ck_reward_cooldown_days_non_negative",
    "ck_reward_purchase_price_paid_positive",
    "ck_reward_purchase_buyer_not_provider",
    "ck_life_balance_target_weekly_xp_target_non_negative",
    "ck_notification_attempts_non_negative",
    "ck_file_size_non_negative",
}

EXPECTED_UNIQUES = {
    "uq_user_tg_user_id",
    "uq_character_user_id",
    "uq_partnership_user_a_id_user_b_id",
    "uq_partnership_invitation_token_hash",
    "uq_wallet_user_id_partnership_id",
    "uq_gold_transaction_idempotency_key",
    "uq_xp_transaction_quest_occurrence_id",
    "uq_quest_revision_template_id_version",
    "uq_quest_occurrence_template_id_scheduled_date",
    "uq_reward_purchase_idempotency_key",
    "uq_file_storage_key",
}

# name -> fragments that must appear in pg_indexes.indexdef
EXPECTED_PARTIAL_UNIQUE_INDEXES = {
    "ux_partnership_active_user_a": ["UNIQUE", "(user_a_id)", "status = 'active'"],
    "ux_partnership_active_user_b": ["UNIQUE", "(user_b_id)", "status = 'active'"],
    "ux_partnership_invitation_pending_creator": ["UNIQUE", "(creator_id)", "'pending'"],
    "ux_notification_dedupe": [
        "UNIQUE",
        "recipient_id, type, entity_id",
        "'UTC'",
        "NULLS NOT DISTINCT",
        "'reminders'",
        "'summary'",
    ],
}

EXPECTED_PRIMARY_KEYS = {
    "character_attribute": ["character_id", "attribute"],
    "achievement_unlock": ["user_id", "code"],
    "life_balance_target": ["user_id", "attribute"],
    "idempotency_key": ["user_id", "key"],
    "quest_streak": ["template_id"],
}


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def rows(sql: str) -> list[tuple[Any, ...]]:
    async def go() -> list[tuple[Any, ...]]:
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                return [tuple(r) for r in (await conn.execute(text(sql))).all()]
        finally:
            await engine.dispose()

    return run(go())


def app_tables() -> set[str]:
    return {
        r[0]
        for r in rows("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        if r[0] != "alembic_version"
    }


def enum_types() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for name, label in rows(
        "SELECT t.typname, e.enumlabel FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid"
        " JOIN pg_namespace n ON n.oid = t.typnamespace WHERE n.nspname = 'public'"
        " ORDER BY t.typname, e.enumsortorder"
    ):
        out.setdefault(name, []).append(label)
    return out


def constraints(kind: str) -> set[str]:
    return {
        r[0]
        for r in rows(
            "SELECT conname FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace"
            f" WHERE n.nspname = 'public' AND c.contype = '{kind}'"
        )
    }


def trigger_function_exists() -> bool:
    return bool(rows("SELECT 1 FROM pg_proc WHERE proname = 'partnership_one_active_per_user'"))


def test_downgrade_base_then_upgrade_head_round_trips() -> None:
    cfg = alembic_config()
    command.upgrade(cfg, "head")
    try:
        command.downgrade(cfg, "base")
        assert app_tables() == set()
        assert enum_types() == {}
        assert not trigger_function_exists()
    finally:
        command.upgrade(cfg, "head")
    assert app_tables() == EXPECTED_TABLES
    assert trigger_function_exists()
    # and once more, so the downgrade is proven from a freshly upgraded schema too
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    assert app_tables() == EXPECTED_TABLES


def test_head_has_every_table_and_models_cover_them() -> None:
    assert app_tables() == EXPECTED_TABLES
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_postgres_enums_match_common_enums() -> None:
    expected = {pg_type_name(e): [m.value for m in e] for e in ALL_ENUMS}
    assert enum_types() == expected


def test_check_unique_and_partial_unique_constraints_exist() -> None:
    assert EXPECTED_CHECKS <= constraints("c")
    assert EXPECTED_UNIQUES <= constraints("u")
    indexdefs = dict(
        (r[0], r[1])
        for r in rows("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'")
    )
    for name, fragments in EXPECTED_PARTIAL_UNIQUE_INDEXES.items():
        assert name in indexdefs, name
        for fragment in fragments:
            assert fragment in indexdefs[name], (name, fragment, indexdefs[name])
    assert "ix_journal_event_partnership_id_created_at" in indexdefs
    triggers = rows(
        "SELECT tgname FROM pg_trigger WHERE tgrelid = 'partnership'::regclass AND NOT tgisinternal"
    )
    assert triggers == [("partnership_one_active_per_user",)]


def test_composite_primary_keys() -> None:
    for table, columns in EXPECTED_PRIMARY_KEYS.items():
        got = rows(
            "SELECT a.attname FROM pg_index i"
            " JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)"
            f" WHERE i.indrelid = '\"{table}\"'::regclass AND i.indisprimary"
        )
        assert sorted(r[0] for r in got) == sorted(columns), table


def test_all_timestamps_are_timestamptz_and_ids_bigint() -> None:
    naive = rows(
        "SELECT table_name, column_name FROM information_schema.columns"
        " WHERE table_schema = 'public' AND data_type = 'timestamp without time zone'"
    )
    assert naive == []
    int_ids = rows(
        "SELECT table_name, column_name FROM information_schema.columns"
        " WHERE table_schema = 'public' AND data_type = 'integer'"
        " AND (column_name = 'id' OR column_name LIKE '%\\_id' OR column_name IN"
        " ('ended_by', 'accepted_by', 'proposed_by', 'submitted_by', 'cancelled_by',"
        " 'refunded_by'))"
    )
    assert int_ids == []


def test_no_drift_between_models_and_migration() -> None:
    """Same comparison as ``alembic check``."""

    def diff(conn: Connection) -> list[Any]:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        return list(compare_metadata(ctx, Base.metadata))

    async def go() -> list[Any]:
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                return await conn.run_sync(diff)
        finally:
            await engine.dispose()

    assert run(go()) == []


def test_every_enum_column_uses_a_common_enum() -> None:
    enum_cols = [
        (table.name, col.name, col.type)
        for table in Base.metadata.tables.values()
        for col in table.columns
        if isinstance(col.type, Enum)
    ]
    assert enum_cols
    for table, column, typ in enum_cols:
        assert typ.enum_class in ALL_ENUMS, (table, column)
        assert typ.name == pg_type_name(typ.enum_class), (table, column)
