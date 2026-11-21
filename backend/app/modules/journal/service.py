"""Adventure Journal writes. Every domain records its events through ``record_event`` inside
the transaction that makes the change, so a rolled-back command leaves no journal row.

Payloads denormalize titles and amounts (history survives edits) but never carry a person's
name or free text they typed about themselves: account deletion scrubs ``user``/``character``
and does not rewrite shared journal payloads. ``check_payload`` enforces the name rule for
journal and notification payloads.
"""

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.common.enums import JournalVisibility
from app.modules.journal.models import JournalEvent

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
    session: AsyncSession,
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
    return event
