"""``Idempotency-Key`` handling for money/XP writes (ARCHITECTURE §3 "Concurrency and
idempotency"; used by ``/quests/{id}/submit`` and ``/confirm``, later ``/purchase``).

Protocol, all inside the command's own transaction:

1. ``claim`` inserts ``(user_id, key)`` into ``idempotency_key`` with ``ON CONFLICT DO
   NOTHING``. A concurrent request with the same key blocks on that insert until the first
   transaction ends: if it committed, the row exists and its stored response is replayed; if it
   rolled back, the insert goes through and this request runs the command itself.
2. The command runs; before committing, the service calls ``Claim.store`` with the response.
3. Commit makes the effect and the stored response visible together. A failed command (any
   4xx) rolls the claim back too, so errors are never cached and a retry runs again.

Keys are scoped per user (primary key ``(user_id, key)``), so two users can never collide.
A key is bound to one request: reusing it for another endpoint or another body is refused
(``IdempotencyKeyReusedError``, 422). Stored responses expire after ``TTL`` (24h); an expired
row is replaced on the next claim and ``purge_expired`` deletes the rest.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import Header
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.modules.common.models import IdempotencyKey

HEADER = "Idempotency-Key"
REPLAY_HEADER = "Idempotent-Replayed"
#: Fits every ledger key that embeds it (economy.service.MAX_CLIENT_KEY_LEN) in String(255).
MAX_KEY_LEN = 128
#: Visible ASCII only (UUIDs, ULIDs, base64url...): no spaces or control characters.
KEY_PATTERN = r"^[!-~]+$"
TTL = timedelta(hours=24)
_IN_PROGRESS = "in_progress"

IdempotencyKeyHeader = Annotated[
    str | None,
    Header(
        alias=HEADER,
        min_length=1,
        max_length=MAX_KEY_LEN,
        pattern=KEY_PATTERN,
        description="Retry-safe key (1-128 visible ASCII chars); a repeat with the same key "
        "replays the first response for 24h.",
    ),
]


class IdempotencyKeyReusedError(Exception):
    """The key was already used for a different endpoint or request body."""


def fingerprint(payload: Any) -> str:
    """Stable hash of a JSON-able request body (key order does not matter)."""
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Replay:
    status_code: int
    body: Any

    def response(self) -> JSONResponse:
        return JSONResponse(
            self.body, status_code=self.status_code, headers={REPLAY_HEADER: "true"}
        )


@dataclass(frozen=True, slots=True)
class Claim:
    user_id: int
    key: str
    request_hash: str

    async def store(self, session: AsyncSession, status_code: int, body: Any) -> None:
        """Record the response in the claimed row (same transaction, before commit)."""
        result = await session.execute(
            update(IdempotencyKey)
            .where(IdempotencyKey.user_id == self.user_id, IdempotencyKey.key == self.key)
            .values(
                response={
                    "state": "done",
                    "request_hash": self.request_hash,
                    "status_code": status_code,
                    "body": body,
                }
            )
        )
        if getattr(result, "rowcount", 0) != 1:  # pragma: no cover - the claim was rolled back
            raise RuntimeError("idempotency claim lost before store")


async def claim(
    session: AsyncSession, *, user_id: int, key: str, endpoint: str, request_hash: str
) -> Claim | Replay:
    """Claim ``key`` for this request, or return the stored response of its first use."""
    now = clock.now()
    await session.execute(
        delete(IdempotencyKey).where(
            IdempotencyKey.user_id == user_id,
            IdempotencyKey.key == key,
            IdempotencyKey.created_at <= now - TTL,
        )
    )
    inserted = await session.scalar(
        insert(IdempotencyKey)
        .values(
            user_id=user_id,
            key=key,
            endpoint=endpoint[:255],
            response={"state": _IN_PROGRESS, "request_hash": request_hash},
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=[IdempotencyKey.user_id, IdempotencyKey.key])
        .returning(IdempotencyKey.key)
    )
    if inserted is not None:
        return Claim(user_id=user_id, key=key, request_hash=request_hash)
    row = await session.scalar(
        select(IdempotencyKey)
        .where(IdempotencyKey.user_id == user_id, IdempotencyKey.key == key)
        .execution_options(populate_existing=True)
    )
    assert row is not None
    stored = row.response
    if row.endpoint != endpoint[:255] or stored.get("request_hash") != request_hash:
        raise IdempotencyKeyReusedError
    if stored.get("state") != "done":  # pragma: no cover - rows commit only with a response
        raise IdempotencyKeyReusedError
    return Replay(status_code=int(stored["status_code"]), body=stored["body"])


async def purge_expired(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Delete stored responses older than ``TTL`` (no commit); returns how many."""
    cutoff = (now or clock.now()) - TTL
    result = await session.execute(
        delete(IdempotencyKey).where(IdempotencyKey.created_at <= cutoff)
    )
    return int(getattr(result, "rowcount", 0) or 0)
