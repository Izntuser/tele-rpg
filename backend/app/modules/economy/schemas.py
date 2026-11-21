"""Economy read models. Ledger rows never expose their idempotency key."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.common.enums import GoldTransactionType


class WalletOut(BaseModel):
    wallet_id: int
    partnership_id: int
    balance: int
    #: True for the wallet of an ended partnership: read-only, nothing can be bought with it.
    frozen: bool
    ended_at: datetime | None


class BalanceOut(BaseModel):
    #: The wallet of my active partnership; null without one.
    active: WalletOut | None
    frozen: list[WalletOut]


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    wallet_id: int
    partnership_id: int
    type: GoldTransactionType
    amount: int
    quest_occurrence_id: int | None
    purchase_id: int | None
    created_at: datetime


class LedgerPage(BaseModel):
    items: list[TransactionOut]
    #: Pass as ``cursor`` for the next (older) page; null on the last page.
    next_cursor: str | None
