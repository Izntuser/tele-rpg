"""Gold ledger and wallets (ARCHITECTURE §4 "Rules encoded in services", DECISIONS #4, #5, #16).

Every Gold change goes through ``post``, inside the caller's transaction:

1. the wallet row for ``(user, partnership)`` is created if missing and locked ``FOR UPDATE``;
2. the ledger row is inserted with a globally unique ``idempotency_key`` (``ON CONFLICT DO
   NOTHING``): a second post with the same key raises ``DuplicateLedgerEntryError`` and the
   caller's transaction must roll back, so an effect can never be applied twice;
3. the cached ``wallet.balance`` moves by the same amount; a debit that would make it negative
   raises ``InsufficientGoldError`` before anything is written (the ``balance >= 0`` CHECK is
   the last line of defence).

So ``wallet.balance == sum(gold_transaction.amount)`` holds after every commit. Amounts always
come from server-side data (a quest's ``terms_snapshot``, a reward's price), never a client.

Ledger keys are built here, never from raw client input alone: ``quest:{occurrence_id}``,
``purchase:{user_id}:{client_key}`` (namespaced per user, so two users' Idempotency-Keys can
never collide) and ``refund:{purchase_id}``.

Lock order: callers lock the partnership (``FOR SHARE``) and their own domain rows (quest
template / occurrence, reward) first, then the wallet here, then (quests) the character.
"""

import base64
import binascii
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.common.enums import GoldTransactionType, PartnershipStatus
from app.modules.economy.models import GoldTransaction, Wallet
from app.modules.economy.schemas import BalanceOut, LedgerPage, TransactionOut, WalletOut
from app.modules.partnerships.models import Partnership
from app.modules.users.models import User

#: Longest client Idempotency-Key accepted (core.idempotency); keeps every ledger key that
#: embeds one within gold_transaction.idempotency_key's String(255).
MAX_CLIENT_KEY_LEN = 128
LEDGER_PAGE_MAX = 100


class EconomyError(Exception):
    pass


class InsufficientGoldError(EconomyError):
    """The debit would make the wallet balance negative."""


class DuplicateLedgerEntryError(EconomyError):
    """A ledger row with this idempotency key already exists: the effect was applied before."""


class InvalidCursorError(EconomyError):
    pass


def quest_reward_key(occurrence_id: int) -> str:
    return f"quest:{occurrence_id}"


def purchase_key(user_id: int, client_key: str) -> str:
    """Ledger key of a purchase made with the buyer's ``Idempotency-Key`` (rewards stage)."""
    if not client_key or len(client_key) > MAX_CLIENT_KEY_LEN:
        raise ValueError("client idempotency key must be 1..128 characters")
    return f"purchase:{user_id}:{client_key}"


def refund_key(purchase_id: int) -> str:
    return f"refund:{purchase_id}"


async def lock_wallet(session: AsyncSession, user_id: int, partnership_id: int) -> Wallet:
    """The ``(user, partnership)`` wallet, created with balance 0 if missing, locked ``FOR
    UPDATE`` and re-read from the database."""
    await session.execute(
        insert(Wallet)
        .values(user_id=user_id, partnership_id=partnership_id, balance=0)
        .on_conflict_do_nothing(index_elements=[Wallet.user_id, Wallet.partnership_id])
    )
    wallet = await session.scalar(
        select(Wallet)
        .where(Wallet.user_id == user_id, Wallet.partnership_id == partnership_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert wallet is not None
    return wallet


async def post(
    session: AsyncSession,
    *,
    user_id: int,
    partnership_id: int,
    type: GoldTransactionType,
    amount: int,
    key: str,
    quest_occurrence_id: int | None = None,
    purchase_id: int | None = None,
) -> GoldTransaction:
    """Apply one ledger entry and the matching balance change (no commit)."""
    wallet = await lock_wallet(session, user_id, partnership_id)
    if wallet.balance + amount < 0:
        raise InsufficientGoldError
    tx_id = await session.scalar(
        insert(GoldTransaction)
        .values(
            wallet_id=wallet.id,
            user_id=user_id,
            partnership_id=partnership_id,
            type=type,
            amount=amount,
            quest_occurrence_id=quest_occurrence_id,
            purchase_id=purchase_id,
            idempotency_key=key,
        )
        .on_conflict_do_nothing(index_elements=[GoldTransaction.idempotency_key])
        .returning(GoldTransaction.id)
    )
    if tx_id is None:
        raise DuplicateLedgerEntryError(key)
    wallet.balance += amount
    await session.flush()
    tx = await session.get(GoldTransaction, tx_id)
    assert tx is not None
    return tx


async def credit_quest_reward(
    session: AsyncSession, *, user_id: int, partnership_id: int, occurrence_id: int, gold: int
) -> GoldTransaction:
    """The quest's Gold (``>= 0``, from its terms snapshot), once per occurrence."""
    return await post(
        session,
        user_id=user_id,
        partnership_id=partnership_id,
        type=GoldTransactionType.QUEST_REWARD,
        amount=gold,
        key=quest_reward_key(occurrence_id),
        quest_occurrence_id=occurrence_id,
    )


# --- read models -----------------------------------------------------------------------------


async def balance(session: AsyncSession, user: User) -> BalanceOut:
    """My wallet in the active partnership (null without one) plus the frozen wallets of ended
    partnerships (readable; refunds may still credit them, nothing can be bought with them)."""
    rows = (
        await session.execute(
            select(Wallet, Partnership)
            .join(Partnership, Partnership.id == Wallet.partnership_id)
            .where(Wallet.user_id == user.id)
            .order_by(Wallet.id)
        )
    ).all()
    active: WalletOut | None = None
    frozen: list[WalletOut] = []
    for wallet, partnership in rows:
        out = WalletOut(
            wallet_id=wallet.id,
            partnership_id=partnership.id,
            balance=wallet.balance,
            frozen=partnership.status != PartnershipStatus.ACTIVE,
            ended_at=partnership.ended_at,
        )
        if out.frozen:
            frozen.append(out)
        else:
            active = out
    return BalanceOut(active=active, frozen=frozen)


@dataclass(frozen=True, slots=True)
class _Cursor:
    before_id: int


def encode_cursor(before_id: int) -> str:
    return base64.urlsafe_b64encode(f"tx:{before_id}".encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> _Cursor:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        prefix, _, value = raw.partition(":")
        before_id = int(value)
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise InvalidCursorError from None
    if prefix != "tx" or before_id <= 0 or not value.isdigit():
        raise InvalidCursorError
    return _Cursor(before_id)


async def transactions(
    session: AsyncSession, user: User, *, cursor: str | None, limit: int
) -> LedgerPage:
    """My own ledger rows across all my wallets, newest first, keyset-paginated by id."""
    query = select(GoldTransaction).where(GoldTransaction.user_id == user.id)
    if cursor is not None:
        query = query.where(GoldTransaction.id < decode_cursor(cursor).before_id)
    rows = list(await session.scalars(query.order_by(GoldTransaction.id.desc()).limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    return LedgerPage(
        items=[TransactionOut.model_validate(r) for r in rows],
        next_cursor=encode_cursor(rows[-1].id) if more and rows else None,
    )
