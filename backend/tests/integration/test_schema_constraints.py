"""The database itself rejects invalid money, ledger, quest and pairing states (ARCHITECTURE §4).

Each rejection is asserted by constraint name, so a test cannot pass because some *other*
constraint happened to fire.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import Executable, func, insert, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.common.enums import (
    Attribute,
    GoldTransactionType,
    InvitationStatus,
    NotificationCategory,
    PartnershipStatus,
    Recurrence,
    SubmissionReviewStatus,
)
from app.modules.economy.models import GoldTransaction, Wallet
from app.modules.notifications.models import Notification
from app.modules.partnerships.models import Partnership, PartnershipInvitation
from app.modules.progression.models import XpTransaction
from app.modules.quests.models import QuestOccurrence, QuestSubmission, QuestTemplate
from app.modules.rewards.models import Reward, RewardPurchase
from app.modules.users.models import Character, CharacterAttribute
from tests import factories as f


def constraint_of(exc: BaseException) -> str | None:
    """The violated constraint's name, read from the asyncpg error in the cause chain."""
    seen: BaseException | None = exc
    while seen is not None:
        name = getattr(seen, "constraint_name", None)
        if name:
            return str(name)
        seen = seen.__cause__ or getattr(seen, "orig", None)
    return None


async def assert_rejected(session: AsyncSession, stmt: Executable, constraint: str) -> None:
    with pytest.raises(IntegrityError) as info:
        async with session.begin_nested():
            await session.execute(stmt)
    assert constraint_of(info.value) == constraint, info.value


async def accepted(session: AsyncSession, stmt: Executable) -> None:
    async with session.begin_nested():
        await session.execute(stmt)


Pair = tuple[Any, Any, Partnership]


async def pair(session: AsyncSession) -> Pair:
    a = await f.create_user(session)
    b = await f.create_user(session)
    return a, b, await f.create_partnership(session, a, b)


# --- money -----------------------------------------------------------------------------------


async def test_wallet_balance_cannot_go_negative(session: AsyncSession) -> None:
    a, _, p = await pair(session)
    wallet = await f.create_wallet(session, a, p, balance=10)
    await assert_rejected(
        session,
        update(Wallet).where(Wallet.id == wallet.id).values(balance=Wallet.balance - 11),
        "ck_wallet_balance_non_negative",
    )
    await accepted(session, update(Wallet).where(Wallet.id == wallet.id).values(balance=0))


async def test_wallet_insert_with_negative_balance_rejected(session: AsyncSession) -> None:
    a, _, p = await pair(session)
    await assert_rejected(
        session,
        insert(Wallet).values(user_id=a.id, partnership_id=p.id, balance=-1),
        "ck_wallet_balance_non_negative",
    )


async def test_one_wallet_per_user_and_partnership(session: AsyncSession) -> None:
    a, _, p = await pair(session)
    await f.create_wallet(session, a, p)
    await assert_rejected(
        session,
        insert(Wallet).values(user_id=a.id, partnership_id=p.id),
        "uq_wallet_user_id_partnership_id",
    )


async def test_duplicate_gold_transaction_idempotency_key_rejected(session: AsyncSession) -> None:
    a, _, p = await pair(session)
    wallet = await f.create_wallet(session, a, p)
    row = {
        "wallet_id": wallet.id,
        "user_id": a.id,
        "partnership_id": p.id,
        "type": GoldTransactionType.QUEST_REWARD,
        "amount": 50,
        "idempotency_key": "quest:1",
    }
    await accepted(session, insert(GoldTransaction).values(**row))
    await assert_rejected(
        session,
        insert(GoldTransaction).values(**{**row, "amount": 20}),
        "uq_gold_transaction_idempotency_key",
    )


@pytest.mark.parametrize(
    ("tx_type", "amount", "ok"),
    [
        (GoldTransactionType.QUEST_REWARD, 50, True),
        (GoldTransactionType.QUEST_REWARD, 0, True),
        (GoldTransactionType.QUEST_REWARD, -50, False),
        (GoldTransactionType.REWARD_PURCHASE, -40, True),
        (GoldTransactionType.REWARD_PURCHASE, 40, False),
        (GoldTransactionType.REWARD_PURCHASE, 0, False),
        (GoldTransactionType.REWARD_REFUND, 40, True),
        (GoldTransactionType.REWARD_REFUND, -40, False),
        (GoldTransactionType.ADJUSTMENT, -5, True),
        (GoldTransactionType.ADJUSTMENT, 5, True),
    ],
)
async def test_gold_transaction_sign_matches_type(
    session: AsyncSession, tx_type: GoldTransactionType, amount: int, ok: bool
) -> None:
    a, _, p = await pair(session)
    wallet = await f.create_wallet(session, a, p)
    stmt = insert(GoldTransaction).values(
        wallet_id=wallet.id,
        user_id=a.id,
        partnership_id=p.id,
        type=tx_type,
        amount=amount,
        idempotency_key=f"sign:{tx_type}:{amount}",
    )
    if ok:
        await accepted(session, stmt)
    else:
        await assert_rejected(session, stmt, "ck_gold_transaction_amount_sign_matches_type")


async def test_reward_quantity_remaining_cannot_go_negative(session: AsyncSession) -> None:
    a, _, p = await pair(session)
    reward = await f.create_reward(session, p, a, quantity_limit=1)
    await accepted(
        session,
        update(Reward)
        .where(Reward.id == reward.id)
        .values(quantity_remaining=Reward.quantity_remaining - 1),
    )
    await assert_rejected(
        session,
        update(Reward)
        .where(Reward.id == reward.id)
        .values(quantity_remaining=Reward.quantity_remaining - 1),
        "ck_reward_quantity_remaining_non_negative",
    )


async def test_reward_price_must_be_positive(session: AsyncSession) -> None:
    a, _, p = await pair(session)
    await assert_rejected(
        session,
        insert(Reward).values(partnership_id=p.id, creator_id=a.id, title="Free", price=0),
        "ck_reward_price_positive",
    )


async def test_purchase_rules(session: AsyncSession) -> None:
    a, b, p = await pair(session)
    reward = await f.create_reward(session, p, a)
    row = {
        "reward_id": reward.id,
        "partnership_id": p.id,
        "buyer_id": b.id,
        "provider_id": a.id,
        "price_paid": 40,
        "reward_snapshot": {"title": reward.title},
        "idempotency_key": "k1",
    }
    await accepted(session, insert(RewardPurchase).values(**row))
    await assert_rejected(
        session,
        insert(RewardPurchase).values(**row),
        "uq_reward_purchase_idempotency_key",
    )
    await assert_rejected(
        session,
        insert(RewardPurchase).values(**{**row, "idempotency_key": "k2", "buyer_id": a.id}),
        "ck_reward_purchase_buyer_not_provider",
    )
    await assert_rejected(
        session,
        insert(RewardPurchase).values(**{**row, "idempotency_key": "k3", "price_paid": 0}),
        "ck_reward_purchase_price_paid_positive",
    )


# --- quests and progression ------------------------------------------------------------------


async def test_duplicate_occurrence_per_template_and_date_rejected(session: AsyncSession) -> None:
    a, b, p = await pair(session)
    template = await f.create_quest_template(session, p, a, b, recurrence=Recurrence.DAILY)
    day = date(2026, 1, 15)
    await f.create_quest_occurrence(session, template, scheduled_date=day)
    await assert_rejected(
        session,
        insert(QuestOccurrence).values(
            template_id=template.id,
            assignee_id=b.id,
            status="active",
            scheduled_date=day,
            terms_snapshot={},
        ),
        "uq_quest_occurrence_template_id_scheduled_date",
    )
    # Next day is fine.
    await f.create_quest_occurrence(session, template, scheduled_date=day + timedelta(days=1))


async def test_quest_template_rules(session: AsyncSession) -> None:
    a, b, p = await pair(session)
    base: dict[str, Any] = {
        "partnership_id": p.id,
        "creator_id": a.id,
        "assignee_id": b.id,
        "title": "Run",
        "attribute": Attribute.PHYSICAL,
        "difficulty": "normal",
        "gold": 50,
        "recurrence": "once",
    }
    await accepted(session, insert(QuestTemplate).values(**base))
    await assert_rejected(
        session,
        insert(QuestTemplate).values(**{**base, "assignee_id": a.id}),
        "ck_quest_template_assignee_not_creator",
    )
    for gold in (-1, 1001):
        await assert_rejected(
            session,
            insert(QuestTemplate).values(**{**base, "gold": gold}),
            "ck_quest_template_gold_range",
        )
    await accepted(session, insert(QuestTemplate).values(**{**base, "gold": 1000}))
    await assert_rejected(
        session,
        insert(QuestTemplate).values(**{**base, "recurrence": "daily", "deadline_at": func.now()}),
        "ck_quest_template_deadline_only_for_once",
    )


async def test_redo_requires_review_comment(session: AsyncSession) -> None:
    a, b, p = await pair(session)
    occurrence = await f.create_quest_occurrence(
        session, await f.create_quest_template(session, p, a, b)
    )
    row = {
        "occurrence_id": occurrence.id,
        "submitted_by": b.id,
        "review_status": SubmissionReviewStatus.REDO,
    }
    for comment in (None, "", "   "):
        await assert_rejected(
            session,
            insert(QuestSubmission).values(**row, review_comment=comment),
            "ck_quest_submission_redo_requires_comment",
        )
    await accepted(session, insert(QuestSubmission).values(**row, review_comment="Add a photo"))


async def test_one_xp_transaction_per_occurrence(session: AsyncSession) -> None:
    a, b, p = await pair(session)
    occurrence = await f.create_quest_occurrence(
        session, await f.create_quest_template(session, p, a, b)
    )
    row = {
        "user_id": b.id,
        "quest_occurrence_id": occurrence.id,
        "xp": 50,
        "attribute": Attribute.PHYSICAL,
        "attribute_xp": 50,
    }
    await accepted(session, insert(XpTransaction).values(**row))
    await assert_rejected(
        session,
        insert(XpTransaction).values(**row),
        "uq_xp_transaction_quest_occurrence_id",
    )


async def test_character_xp_non_negative(session: AsyncSession) -> None:
    user = await f.create_user(session)
    await assert_rejected(
        session,
        update(Character).where(Character.user_id == user.id).values(total_xp=-1),
        "ck_character_total_xp_non_negative",
    )
    await assert_rejected(
        session,
        update(CharacterAttribute).values(xp=-1),
        "ck_character_attribute_xp_non_negative",
    )


# --- partnerships ----------------------------------------------------------------------------


@pytest.mark.parametrize("order", ["equal", "reversed"])
async def test_partnership_requires_user_a_less_than_user_b(
    session: AsyncSession, order: str
) -> None:
    a = await f.create_user(session)
    b = await f.create_user(session)
    lo, hi = sorted((a.id, b.id))
    first, second = (lo, lo) if order == "equal" else (hi, lo)
    await assert_rejected(
        session,
        insert(Partnership).values(user_a_id=first, user_b_id=second),
        "ck_partnership_users_ordered",
    )


async def test_same_pair_has_one_row(session: AsyncSession) -> None:
    a, b, p = await pair(session)
    await accepted(
        session, update(Partnership).where(Partnership.id == p.id).values(status="ended")
    )
    await assert_rejected(
        session,
        insert(Partnership).values(user_a_id=p.user_a_id, user_b_id=p.user_b_id),
        "uq_partnership_user_a_id_user_b_id",
    )


async def _three_users(session: AsyncSession) -> list[int]:
    return sorted([(await f.create_user(session)).id for _ in range(3)])


CLASHES = [
    ((0, 1), (0, 2)),  # same user as user_a in both
    ((0, 2), (1, 2)),  # same user as user_b in both
    ((0, 1), (1, 2)),  # user_b of the first is user_a of the second
    ((1, 2), (0, 1)),  # user_a of the first is user_b of the second
]


@pytest.mark.parametrize(("first", "second"), CLASHES)
async def test_second_active_partnership_for_a_user_rejected(
    session: AsyncSession, first: tuple[int, int], second: tuple[int, int]
) -> None:
    ids = await _three_users(session)
    await accepted(
        session,
        insert(Partnership).values(user_a_id=ids[first[0]], user_b_id=ids[first[1]]),
    )
    await assert_rejected(
        session,
        insert(Partnership).values(user_a_id=ids[second[0]], user_b_id=ids[second[1]]),
        "partnership_one_active_per_user",
    )


@pytest.mark.parametrize(
    ("first", "second", "index"),
    [
        (*CLASHES[0], "ux_partnership_active_user_a"),
        (*CLASHES[1], "ux_partnership_active_user_b"),
    ],
)
async def test_partial_unique_indexes_back_up_the_trigger(
    session: AsyncSession, first: tuple[int, int], second: tuple[int, int], index: str
) -> None:
    """With the (BEFORE) trigger disabled inside this rolled-back transaction, the partial
    unique indexes alone still reject a user twice in the same column."""
    await session.execute(
        text("ALTER TABLE partnership DISABLE TRIGGER partnership_one_active_per_user")
    )
    ids = await _three_users(session)
    await accepted(
        session,
        insert(Partnership).values(user_a_id=ids[first[0]], user_b_id=ids[first[1]]),
    )
    await assert_rejected(
        session,
        insert(Partnership).values(user_a_id=ids[second[0]], user_b_id=ids[second[1]]),
        index,
    )


async def test_ended_partnership_frees_users_and_reactivation_is_checked(
    session: AsyncSession,
) -> None:
    ids = await _three_users(session)
    old = (
        await session.execute(
            insert(Partnership).values(user_a_id=ids[0], user_b_id=ids[1]).returning(Partnership.id)
        )
    ).scalar_one()
    await accepted(
        session,
        update(Partnership).where(Partnership.id == old).values(status=PartnershipStatus.ENDED),
    )
    # user 1 may now pair with user 2 (as user_a: the cross-column case)
    await accepted(session, insert(Partnership).values(user_a_id=ids[1], user_b_id=ids[2]))
    # re-activating the old row (re-pair) while user 1 is taken is rejected
    await assert_rejected(
        session,
        update(Partnership).where(Partnership.id == old).values(status=PartnershipStatus.ACTIVE),
        "partnership_one_active_per_user",
    )
    # an update that does not activate anything is not blocked by the trigger
    await accepted(
        session, update(Partnership).where(Partnership.id == old).values(ended_by=ids[0])
    )


async def test_second_pending_invitation_per_creator_rejected(session: AsyncSession) -> None:
    creator = await f.create_user(session)
    first = await f.create_invitation(session, creator)
    row = {"creator_id": creator.id, "token_hash": "b" * 64, "expires_at": func.now()}
    await assert_rejected(
        session,
        insert(PartnershipInvitation).values(**row),
        "ux_partnership_invitation_pending_creator",
    )
    await accepted(
        session,
        update(PartnershipInvitation)
        .where(PartnershipInvitation.id == first.id)
        .values(status=InvitationStatus.REVOKED),
    )
    await accepted(session, insert(PartnershipInvitation).values(**row))
    await assert_rejected(
        session,
        insert(PartnershipInvitation).values(
            **{**row, "status": InvitationStatus.EXPIRED, "creator_id": first.creator_id}
        ),
        "uq_partnership_invitation_token_hash",
    )


# --- notifications ---------------------------------------------------------------------------


async def test_reminder_and_summary_dedupe(session: AsyncSession) -> None:
    user = await f.create_user(session)

    def note(category: NotificationCategory, entity_id: int | None, hour: int) -> Executable:
        return insert(Notification).values(
            recipient_id=user.id,
            type=f"{category}_t",
            category=category,
            entity_id=entity_id,
            send_after=func.make_timestamptz(2026, 1, 15, hour, 0, 0, "UTC"),
        )

    await accepted(session, note(NotificationCategory.REMINDERS, 7, 8))
    await assert_rejected(
        session, note(NotificationCategory.REMINDERS, 7, 20), "ux_notification_dedupe"
    )
    await accepted(session, note(NotificationCategory.REMINDERS, 8, 20))  # other entity
    # The daily summary has no entity: NULLS NOT DISTINCT still dedupes it.
    await accepted(session, note(NotificationCategory.SUMMARY, None, 9))
    await assert_rejected(
        session, note(NotificationCategory.SUMMARY, None, 10), "ux_notification_dedupe"
    )
    # Other categories are never deduped.
    await accepted(session, note(NotificationCategory.QUESTS, 7, 8))
    await accepted(session, note(NotificationCategory.QUESTS, 7, 8))


# --- factories -------------------------------------------------------------------------------


async def test_factories_build_consistent_rows(session: AsyncSession) -> None:
    a, b, p = await pair(session)
    assert p.user_a_id < p.user_b_id
    character = (
        await session.execute(select(Character).where(Character.user_id == a.id))
    ).scalar_one()
    attrs = (
        await session.execute(
            select(CharacterAttribute.attribute).where(
                CharacterAttribute.character_id == character.id
            )
        )
    ).scalars()
    assert set(attrs) == set(Attribute)

    wallet = await f.create_wallet(session, b, p, balance=75)
    ledger = (
        await session.execute(
            select(func.sum(GoldTransaction.amount)).where(GoldTransaction.wallet_id == wallet.id)
        )
    ).scalar_one()
    assert ledger == wallet.balance == 75

    template = await f.create_quest_template(session, p, a, b)
    occurrence = await f.create_quest_occurrence(session, template)
    assert occurrence.assignee_id == b.id
    assert occurrence.terms_snapshot["gold"] == template.gold
    reward = await f.create_reward(session, p, a, quantity_limit=3)
    assert reward.quantity_remaining == 3


# --- concurrency -----------------------------------------------------------------------------


async def test_concurrent_cross_partnerships_only_one_wins(
    independent_sessions: async_sessionmaker[AsyncSession],
) -> None:
    """x<y<z. T1 activates (x, y); T2 concurrently activates (y, z). y is user_b in one and
    user_a in the other, so no unique index sees the clash: the trigger's advisory lock makes T2
    wait for T1 and then reject."""
    async with independent_sessions() as setup:
        ids = sorted([(await f.create_user(setup)).id for _ in range(3)])
        await setup.commit()

    async with independent_sessions() as t1, independent_sessions() as t2:
        await t1.execute(insert(Partnership).values(user_a_id=ids[0], user_b_id=ids[1]))

        async def second() -> None:
            await t2.execute(insert(Partnership).values(user_a_id=ids[1], user_b_id=ids[2]))
            await t2.commit()

        task = asyncio.create_task(second())
        await asyncio.sleep(0.3)
        assert not task.done(), "T2 should be blocked on T1's advisory lock"
        await t1.commit()
        with pytest.raises(IntegrityError) as info:
            await task
        assert constraint_of(info.value) == "partnership_one_active_per_user"
        await t2.rollback()

    async with independent_sessions() as check:
        active = (
            await check.execute(
                select(func.count()).select_from(Partnership).where(Partnership.status == "active")
            )
        ).scalar_one()
    assert active == 1


async def test_concurrent_wallet_debits_never_go_negative(
    independent_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with independent_sessions() as setup:
        a = await f.create_user(setup)
        b = await f.create_user(setup)
        p = await f.create_partnership(setup, a, b)
        wallet = await f.create_wallet(setup, a, p, balance=40)
        await setup.commit()

    async def debit() -> bool:
        async with independent_sessions() as s:
            try:
                await s.execute(
                    update(Wallet).where(Wallet.id == wallet.id).values(balance=Wallet.balance - 40)
                )
                await s.commit()
                return True
            except IntegrityError:
                await s.rollback()
                return False

    runs: list[Callable[[], Awaitable[bool]]] = [debit] * 5
    results = await asyncio.gather(*(run() for run in runs))
    assert results.count(True) == 1
    async with independent_sessions() as check:
        balance = (
            await check.execute(select(Wallet.balance).where(Wallet.id == wallet.id))
        ).scalar_one()
    assert balance == 0
