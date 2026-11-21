"""Async factories for test data. Each one adds rows and flushes (never commits), so it works
with both the rolled-back ``session`` fixture and ``independent_sessions`` (commit yourself).

Factories keep the documented invariants: a user gets a character with all 6 attribute rows,
partnerships are stored with ``user_a_id < user_b_id``, and a wallet created with a balance
gets a matching ``adjustment`` ledger row so ``balance == sum(gold_transaction.amount)``.
"""

import itertools
import secrets
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.modules.common.enums import (
    Attribute,
    ConfirmationMode,
    Difficulty,
    GoldTransactionType,
    InvitationStatus,
    Locale,
    PartnershipStatus,
    QuestOccurrenceStatus,
    QuestTemplateStatus,
    Recurrence,
    RewardStatus,
)
from app.modules.economy.models import GoldTransaction, Wallet
from app.modules.partnerships.models import Partnership, PartnershipInvitation
from app.modules.quests.models import QuestOccurrence, QuestTemplate
from app.modules.rewards.models import Reward
from app.modules.users.models import Character, CharacterAttribute, User

_seq = itertools.count(1)


def _next() -> int:
    return next(_seq)


async def create_user(
    session: AsyncSession,
    *,
    display_name: str | None = None,
    tg_user_id: int | None = None,
    locale: Locale = Locale.EN,
    timezone: str = "UTC",
    with_character: bool = True,
    **overrides: Any,
) -> User:
    n = _next()
    user = User(
        tg_user_id=tg_user_id if tg_user_id is not None else 900_000_000 + n,
        tg_username=f"user{n}",
        display_name=display_name or f"User {n}",
        locale=locale,
        timezone=timezone,
        **overrides,
    )
    session.add(user)
    await session.flush()
    if with_character:
        await create_character(session, user)
    return user


async def create_character(
    session: AsyncSession, user: User, *, name: str | None = None, total_xp: int = 0
) -> Character:
    character = Character(user_id=user.id, name=name or user.display_name, total_xp=total_xp)
    session.add(character)
    await session.flush()
    session.add_all(
        CharacterAttribute(character_id=character.id, attribute=attr, xp=0) for attr in Attribute
    )
    await session.flush()
    return character


async def create_partnership(
    session: AsyncSession,
    user1: User,
    user2: User,
    *,
    status: PartnershipStatus = PartnershipStatus.ACTIVE,
) -> Partnership:
    a, b = sorted((user1.id, user2.id))
    now = clock.now()
    partnership = Partnership(
        user_a_id=a,
        user_b_id=b,
        status=status,
        accepted_at=now,
        ended_at=now if status == PartnershipStatus.ENDED else None,
    )
    session.add(partnership)
    await session.flush()
    return partnership


async def create_invitation(
    session: AsyncSession,
    creator: User,
    *,
    status: InvitationStatus = InvitationStatus.PENDING,
    expires_at: datetime | None = None,
) -> PartnershipInvitation:
    invitation = PartnershipInvitation(
        creator_id=creator.id,
        token_hash=secrets.token_hex(32),
        status=status,
        expires_at=expires_at or clock.now() + timedelta(days=7),
    )
    session.add(invitation)
    await session.flush()
    return invitation


async def create_wallet(
    session: AsyncSession, user: User, partnership: Partnership, *, balance: int = 0
) -> Wallet:
    wallet = Wallet(user_id=user.id, partnership_id=partnership.id, balance=balance)
    session.add(wallet)
    await session.flush()
    if balance:
        session.add(
            GoldTransaction(
                wallet_id=wallet.id,
                user_id=user.id,
                partnership_id=partnership.id,
                type=GoldTransactionType.ADJUSTMENT,
                amount=balance,
                idempotency_key=f"factory:{secrets.token_hex(8)}",
            )
        )
        await session.flush()
    return wallet


async def create_quest_template(
    session: AsyncSession,
    partnership: Partnership,
    creator: User,
    assignee: User,
    *,
    title: str | None = None,
    attribute: Attribute = Attribute.PHYSICAL,
    difficulty: Difficulty = Difficulty.NORMAL,
    gold: int = 50,
    recurrence: Recurrence = Recurrence.ONCE,
    confirmation: ConfirmationMode = ConfirmationMode.MANUAL,
    status: QuestTemplateStatus = QuestTemplateStatus.ACTIVE,
    **overrides: Any,
) -> QuestTemplate:
    template = QuestTemplate(
        partnership_id=partnership.id,
        creator_id=creator.id,
        assignee_id=assignee.id,
        title=title or f"Quest {_next()}",
        attribute=attribute,
        difficulty=difficulty,
        gold=gold,
        recurrence=recurrence,
        confirmation=confirmation,
        status=status,
        **overrides,
    )
    session.add(template)
    await session.flush()
    return template


def terms_of(template: QuestTemplate, *, xp: int = 50) -> dict[str, Any]:
    return {
        "title": template.title,
        "description": template.description,
        "attribute": template.attribute.value,
        "difficulty": template.difficulty.value,
        "gold": template.gold,
        "xp": xp,
        "deadline": template.deadline_at.isoformat() if template.deadline_at else None,
        "confirmation": template.confirmation.value,
        "photo_required": template.photo_required,
    }


async def create_quest_occurrence(
    session: AsyncSession,
    template: QuestTemplate,
    *,
    status: QuestOccurrenceStatus = QuestOccurrenceStatus.ACTIVE,
    scheduled_date: date | None = None,
    **overrides: Any,
) -> QuestOccurrence:
    occurrence = QuestOccurrence(
        template_id=template.id,
        assignee_id=template.assignee_id,
        status=status,
        scheduled_date=scheduled_date or clock.now().date(),
        terms_snapshot=terms_of(template),
        **overrides,
    )
    session.add(occurrence)
    await session.flush()
    return occurrence


async def create_reward(
    session: AsyncSession,
    partnership: Partnership,
    creator: User,
    *,
    title: str | None = None,
    price: int = 40,
    quantity_limit: int | None = None,
    cooldown_days: int | None = None,
    status: RewardStatus = RewardStatus.ACTIVE,
    **overrides: Any,
) -> Reward:
    reward = Reward(
        partnership_id=partnership.id,
        creator_id=creator.id,
        title=title or f"Reward {_next()}",
        price=price,
        quantity_limit=quantity_limit,
        quantity_remaining=quantity_limit,
        cooldown_days=cooldown_days,
        status=status,
        **overrides,
    )
    session.add(reward)
    await session.flush()
    return reward
