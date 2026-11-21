"""A seeded random walk over quest and economy operations (create, accept, submit, confirm by the
right or wrong member, redo, cancel, Gold debits, and the shop: create rewards, purchase, refund
by the buyer or provider, request) by both members of a partnership. After every step:
wallet.balance == sum(gold_transaction.amount), no negative balance, character total_xp ==
sum(xp_transaction.xp), every attribute's xp == its xp_transactions, exactly one Gold and one
XP row per completed occurrence, one debit per purchase and one credit per refunded purchase."""

import random
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.common.enums import (
    Attribute,
    ConfirmationMode,
    Difficulty,
    GoldTransactionType,
    QuestOccurrenceStatus,
    QuestTemplateStatus,
    Recurrence,
    RewardPurchaseStatus,
)
from app.modules.economy import service as economy
from app.modules.economy.models import GoldTransaction, Wallet
from app.modules.inventory import service as inventory
from app.modules.progression.models import XpTransaction
from app.modules.quests import completion, service
from app.modules.quests.models import QuestOccurrence, QuestTemplate
from app.modules.quests.schemas import ConfirmIn, QuestCreate, RedoIn, SubmitIn
from app.modules.rewards import service as rewards
from app.modules.rewards.models import Reward, RewardPurchase
from app.modules.rewards.schemas import RewardCreate
from app.modules.users.models import User
from tests.integration.completion_support import assert_ledger_invariants, count, pair

STEPS = 120


async def _user(session: AsyncSession, user_id: int) -> User:
    user = await session.get(User, user_id, populate_existing=True)
    assert user is not None
    return user


async def _occurrences(
    session: AsyncSession, status: QuestOccurrenceStatus
) -> list[tuple[int, int, int]]:
    """(occurrence id, creator id, assignee id) in ``status``."""
    rows = await session.execute(
        select(QuestOccurrence.id, QuestTemplate.creator_id, QuestTemplate.assignee_id)
        .join(QuestTemplate, QuestTemplate.id == QuestOccurrence.template_id)
        .where(QuestOccurrence.status == status)
        .order_by(QuestOccurrence.id)
    )
    return [tuple(r) for r in rows.all()]  # type: ignore[misc]


async def _offered_templates(session: AsyncSession) -> list[tuple[int, int]]:
    rows = await session.execute(
        select(QuestTemplate.id, QuestTemplate.assignee_id)
        .where(QuestTemplate.status == QuestTemplateStatus.OFFERED)
        .order_by(QuestTemplate.id)
    )
    return [tuple(r) for r in rows.all()]  # type: ignore[misc]


async def _check(session: AsyncSession) -> None:
    await assert_ledger_invariants(session)
    completed = await count(
        session, QuestOccurrence, QuestOccurrence.status == QuestOccurrenceStatus.COMPLETED
    )
    rewards = await count(
        session, GoldTransaction, GoldTransaction.type == GoldTransactionType.QUEST_REWARD
    )
    assert rewards == completed
    assert await count(session, XpTransaction) == completed
    unpaid = await session.scalar(
        select(func.count())
        .select_from(QuestOccurrence)
        .outerjoin(XpTransaction, XpTransaction.quest_occurrence_id == QuestOccurrence.id)
        .where(QuestOccurrence.status == QuestOccurrenceStatus.COMPLETED)
        .where(XpTransaction.id.is_(None))
    )
    assert unpaid == 0
    purchases = await count(session, RewardPurchase)
    debits = await count(
        session, GoldTransaction, GoldTransaction.type == GoldTransactionType.REWARD_PURCHASE
    )
    assert debits == purchases
    refunded = await count(
        session, RewardPurchase, RewardPurchase.status == RewardPurchaseStatus.REFUNDED
    )
    credits = await count(
        session, GoldTransaction, GoldTransaction.type == GoldTransactionType.REWARD_REFUND
    )
    assert credits == refunded


@pytest.mark.parametrize("seed", [1, 2, 3])
async def test_random_operations_keep_the_ledger_consistent(
    session: AsyncSession, seed: int
) -> None:
    rng = random.Random(seed)
    a, b, partnership = await pair(session)
    members = [a.id, b.id]
    partnership_id = partnership.id
    await session.commit()
    stats: dict[str, int] = {}

    async def create() -> None:
        creator = await _user(session, rng.choice(members))
        data: dict[str, Any] = {
            "title": f"Quest {rng.randint(1, 10_000)}",
            "attribute": rng.choice(list(Attribute)),
            "difficulty": rng.choice(list(Difficulty)),
            "gold": rng.choice([0, 1, 10, 50, 250, 1000]),
            "confirmation": rng.choice(list(ConfirmationMode)),
            "recurrence": rng.choice([Recurrence.ONCE, Recurrence.ONCE, Recurrence.DAILY]),
        }
        await service.create(session, creator, get_settings(), QuestCreate(**data))

    async def accept() -> None:
        offered = await _offered_templates(session)
        if offered:
            template_id, assignee = rng.choice(offered)
            await service.accept(session, await _user(session, assignee), template_id=template_id)

    async def submit() -> None:
        active = await _occurrences(session, QuestOccurrenceStatus.ACTIVE)
        if active:
            occ, _, assignee = rng.choice(active)
            await completion.submit(session, await _user(session, assignee), occ, SubmitIn())

    async def review(action: str) -> None:
        in_review = await _occurrences(session, QuestOccurrenceStatus.IN_REVIEW)
        if not in_review:
            return
        occ, creator, assignee = rng.choice(in_review)
        # Now and then the wrong member tries (must be refused without any effect).
        actor = await _user(session, assignee if rng.random() < 0.2 else creator)
        if action == "confirm":
            await completion.confirm(session, actor, occ, ConfirmIn())
        else:
            await completion.request_redo(session, actor, occ, RedoIn(reason="again"))

    async def cancel() -> None:
        active = await _occurrences(session, QuestOccurrenceStatus.ACTIVE)
        if active:
            occ, creator, _ = rng.choice(active)
            await service.cancel(session, await _user(session, creator), occurrence_id=occ)

    async def debit() -> None:
        user_id = rng.choice(members)
        balance = await session.scalar(
            select(Wallet.balance).where(
                Wallet.user_id == user_id, Wallet.partnership_id == partnership_id
            )
        )
        amount = rng.randint(1, (balance or 0) + 50)
        await economy.post(
            session,
            user_id=user_id,
            partnership_id=partnership_id,
            type=GoldTransactionType.ADJUSTMENT,
            amount=-amount,
            key=f"test:debit:{seed}:{rng.random()}",
        )
        await session.commit()

    async def create_reward() -> None:
        creator = await _user(session, rng.choice(members))
        await rewards.create(
            session,
            creator,
            RewardCreate(
                title=f"Reward {rng.randint(1, 10_000)}",
                price=rng.choice([1, 10, 40, 120]),
                quantity_limit=rng.choice([None, 1, 2, 5]),
            ),
        )

    async def purchase() -> None:
        reward_ids = list(await session.scalars(select(Reward.id)))
        if reward_ids:
            buyer = await _user(session, rng.choice(members))
            await rewards.purchase(
                session, buyer, rng.choice(reward_ids), client_key=f"walk-{seed}-{rng.random()}"
            )

    async def voucher(action: str) -> None:
        rows = (
            await session.execute(
                select(RewardPurchase.id, RewardPurchase.buyer_id, RewardPurchase.provider_id)
                .where(RewardPurchase.status.not_in(rewards.VOID_STATUSES))
                .order_by(RewardPurchase.id)
            )
        ).all()
        if not rows:
            return
        pid, buyer_id, provider_id = rng.choice(rows)
        actor = await _user(session, rng.choice([buyer_id, provider_id]))
        if action == "refund":
            await inventory.refund(session, actor, pid)
        else:
            await inventory.request(session, actor, pid)

    ops = {
        "create_reward": create_reward,
        "purchase": purchase,
        "refund": lambda: voucher("refund"),
        "request": lambda: voucher("request"),
        "create": create,
        "accept": accept,
        "submit": submit,
        "confirm": lambda: review("confirm"),
        "redo": lambda: review("redo"),
        "cancel": cancel,
        "debit": debit,
    }
    weights = {
        "create_reward": 1,
        "purchase": 3,
        "refund": 2,
        "request": 1,
        "create": 4,
        "accept": 4,
        "submit": 5,
        "confirm": 5,
        "redo": 1,
        "cancel": 1,
        "debit": 2,
    }
    names = list(ops)
    for _ in range(STEPS):
        name = rng.choices(names, weights=[weights[n] for n in names])[0]
        try:
            await ops[name]()
            stats[name] = stats.get(name, 0) + 1
        except (service.QuestError, economy.InsufficientGoldError, rewards.RewardError):
            await session.rollback()
            stats[f"{name}:refused"] = stats.get(f"{name}:refused", 0) + 1
        await _check(session)

    # The walk must actually have paid quests out.
    assert stats.get("confirm", 0) + stats.get("submit", 0) > 5, stats
    assert await count(session, XpTransaction) > 0, stats
    assert stats.get("purchase", 0) > 0 and stats.get("refund", 0) > 0, stats
