"""Adventure Journal writes. Every domain records its events through ``record_event`` inside
the transaction that makes the change, so a rolled-back command leaves no journal row.

Payloads denormalize titles and amounts (history survives edits) but never carry a person's
name or free text they typed about themselves: account deletion scrubs ``user``/``character``
and does not rewrite shared journal payloads. ``check_payload`` enforces the name rule for
journal and notification payloads.

Achievements are evaluated from here: ``record_event`` notes (in ``session.info``) who acted
and which event type, and ``app.modules.achievements.service`` evaluates the noted users in a
``before_commit`` listener, so unlocks commit (or roll back) with the event that earned them.

Reads (``GET /journal``): ``scope=me`` is every event I recorded (private and shared, any
partnership); ``scope=shared`` is the shared events of my active partnership by either member.
Another user's private events are never returned. Keyset pagination on ``id``, newest first.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.modules.common.enums import JournalVisibility
from app.modules.journal.models import JournalEvent
from app.modules.users.models import User
from app.modules.users.service import active_partnership

#: ``session.info`` key: ``{(user_id, partnership_id): {event types}}`` awaiting evaluation.
PENDING_ACHIEVEMENTS = "journal.pending_achievements"
JOURNAL_PAGE_DEFAULT = 30
JOURNAL_PAGE_MAX = 100

Scope = Literal["me", "shared"]

#: Keys that would put a person's name or Telegram handle into a stored payload.
FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "display_name",
        "name",
        "character_name",
        "nickname",
        "username",
        "tg_username",
        "first_name",
        "last_name",
        "full_name",
    }
)


class PayloadNameError(ValueError):
    """A journal or notification payload tried to store a person's name."""


def check_payload(payload: Mapping[str, Any]) -> None:
    """Reject (recursively) any key in FORBIDDEN_PAYLOAD_KEYS."""
    for key, value in payload.items():
        if key.lower() in FORBIDDEN_PAYLOAD_KEYS:
            raise PayloadNameError(f"payload must not contain {key!r}")
        if isinstance(value, Mapping):
            check_payload(value)
        elif isinstance(value, list | tuple):
            for item in value:
                if isinstance(item, Mapping):
                    check_payload(item)


def record_event(
    session: AsyncSession | Session,
    *,
    user_id: int,
    type: str,
    partnership_id: int | None,
    entity_type: str | None,
    entity_id: int | None,
    payload: Mapping[str, Any],
    visibility: JournalVisibility = JournalVisibility.SHARED,
) -> JournalEvent:
    """Add a journal event to the session; it is written with the caller's transaction."""
    check_payload(payload)
    event = JournalEvent(
        user_id=user_id,
        partnership_id=partnership_id,
        type=type,
        visibility=visibility,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=dict(payload),
    )
    session.add(event)
    sync = session.sync_session if isinstance(session, AsyncSession) else session
    pending: dict[tuple[int, int | None], set[str]] = sync.info.setdefault(PENDING_ACHIEVEMENTS, {})
    pending.setdefault((user_id, partnership_id), set()).add(type)
    return event


class JournalEventOut(BaseModel):
    id: int
    type: str
    #: Who recorded it, relative to the reader.
    actor: Literal["me", "companion"]
    visibility: JournalVisibility
    entity_type: str | None
    entity_id: int | None
    payload: dict[str, Any]
    created_at: datetime


class JournalPage(BaseModel):
    items: list[JournalEventOut]
    next_cursor: int | None


async def list_events(
    session: AsyncSession, user: User, *, scope: Scope, cursor: int | None, limit: int
) -> JournalPage:
    """One page of my journal (``me``) or of my active partnership's shared journal."""
    query = select(JournalEvent)
    if scope == "me":
        query = query.where(JournalEvent.user_id == user.id)
    else:
        partnership = await active_partnership(session, user.id)
        if partnership is None:
            return JournalPage(items=[], next_cursor=None)
        query = query.where(
            JournalEvent.partnership_id == partnership.id,
            JournalEvent.visibility == JournalVisibility.SHARED,
        )
    if cursor is not None:
        query = query.where(JournalEvent.id < cursor)
    rows = list(await session.scalars(query.order_by(JournalEvent.id.desc()).limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    return JournalPage(
        items=[
            JournalEventOut(
                id=e.id,
                type=e.type,
                actor="me" if e.user_id == user.id else "companion",
                visibility=e.visibility,
                entity_type=e.entity_type,
                entity_id=e.entity_id,
                payload=e.payload,
                created_at=e.created_at,
            )
            for e in rows
        ],
        next_cursor=rows[-1].id if more and rows else None,
    )


# Registers the before_commit listener that evaluates the noted events (imported last: the
# achievements service imports this module).
from app.modules.achievements import service as _achievements  # noqa: E402,F401
