"""Shared setup for the S08 completion / economy tests (not collected: no ``test_`` prefix)."""

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy import func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import clock
from app.core.config import get_settings
from app.db.session import get_session
from app.modules.auth.jwt import encode_token
from app.modules.common.enums import FileKind
from app.modules.economy.models import GoldTransaction, Wallet
from app.modules.files.models import File
from app.modules.partnerships.models import Partnership
from app.modules.progression.models import XpTransaction
from app.modules.quests import service
from app.modules.quests.schemas import QuestCreate
from app.modules.users.models import Character, CharacterAttribute, User
from tests import factories


def ident(obj: Any) -> int:
    """Primary key without touching attributes: a route that rolls back the shared test
    session (after a 4xx) expires every loaded object."""
    identity = inspect(obj).identity
    assert identity is not None
    return int(identity[0])


def auth(user: User | int, **headers: str) -> dict[str, str]:
    user_id = user if isinstance(user, int) else ident(user)
    token = encode_token(user_id, get_settings().jwt_secret.get_secret_value(), timedelta(hours=1))
    return {"Authorization": f"Bearer {token}", **headers}


async def pair(session: AsyncSession) -> tuple[User, User, Partnership]:
    """(game master, player, their active partnership), both onboarded, with wallets."""
    gm = await factories.create_user(session, onboarded_at=clock.now())
    player = await factories.create_user(session, onboarded_at=clock.now())
    partnership = await factories.create_partnership(session, gm, player)
    await factories.create_wallet(session, gm, partnership)
    await factories.create_wallet(session, player, partnership)
    return gm, player, partnership


async def active_quest(session: AsyncSession, gm: User, player: User, **terms: Any) -> int:
    """Offer a quest through the service and let the player accept it; the occurrence id."""
    values: dict[str, Any] = {"title": "Morning run", "attribute": "physical", "gold": 40}
    values.update(terms)
    created = await service.create(session, gm, get_settings(), QuestCreate(**values))
    if created.occurrence is None:
        occurrence_id = await service.accept(session, player, template_id=created.template.id)
    else:
        occurrence_id = await service.accept(session, player, occurrence_id=created.occurrence.id)
    assert occurrence_id is not None
    return occurrence_id


async def photo(
    session: AsyncSession,
    owner: User,
    kind: FileKind = FileKind.QUEST_PHOTO,
    *,
    partnership: Partnership | None,
) -> File:
    file = File(
        owner_id=owner.id,
        partnership_id=partnership.id if partnership is not None else None,
        kind=kind,
        storage_key=f"test/{secrets.token_hex(8)}",
        mime="image/jpeg",
        size=10,
    )
    session.add(file)
    await session.flush()
    return file


async def wallet_balance(session: AsyncSession, user: User, partnership: Partnership) -> int:
    balance = await session.scalar(
        select(Wallet.balance)
        .where(Wallet.user_id == ident(user), Wallet.partnership_id == ident(partnership))
        .execution_options(populate_existing=True)
    )
    assert balance is not None
    return balance


async def count(session: AsyncSession, model: Any, *where: Any) -> int:
    return (await session.scalar(select(func.count()).select_from(model).where(*where))) or 0


async def assert_ledger_invariants(session: AsyncSession) -> None:
    """wallet.balance == sum(ledger) for every wallet, no negative balance, and every
    character's XP (total and per attribute) == the sum of its xp_transactions."""
    wallets = (
        await session.execute(
            select(Wallet.id, Wallet.balance, func.coalesce(func.sum(GoldTransaction.amount), 0))
            .outerjoin(GoldTransaction, GoldTransaction.wallet_id == Wallet.id)
            .group_by(Wallet.id, Wallet.balance)
        )
    ).all()
    for wallet_id, balance, ledger in wallets:
        assert balance == ledger, f"wallet {wallet_id}: balance {balance} != ledger {ledger}"
        assert balance >= 0, f"wallet {wallet_id} is negative"
    characters = (
        await session.execute(
            select(
                Character.user_id,
                Character.total_xp,
                select(func.coalesce(func.sum(XpTransaction.xp), 0))
                .where(XpTransaction.user_id == Character.user_id)
                .scalar_subquery(),
            )
        )
    ).all()
    for user_id, total_xp, ledger in characters:
        assert total_xp == ledger, f"user {user_id}: total_xp {total_xp} != xp ledger {ledger}"
    attributes = (
        await session.execute(
            select(
                Character.user_id,
                CharacterAttribute.attribute,
                CharacterAttribute.xp,
                select(func.coalesce(func.sum(XpTransaction.attribute_xp), 0))
                .where(
                    XpTransaction.user_id == Character.user_id,
                    XpTransaction.attribute == CharacterAttribute.attribute,
                )
                .scalar_subquery(),
            ).join(CharacterAttribute, CharacterAttribute.character_id == Character.id)
        )
    ).all()
    for user_id, attribute, xp, ledger in attributes:
        assert xp == ledger, f"user {user_id} {attribute}: xp {xp} != ledger {ledger}"


@asynccontextmanager
async def app_client(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP client whose every request gets its own real session (separate connections)."""
    from app.main import create_app

    app = create_app()

    async def _session() -> AsyncIterator[AsyncSession]:
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
