"""Notification outbox writes (ARCHITECTURE §3 "Notifications").

``enqueue`` only adds a ``pending`` row to the caller's transaction; the dispatcher (a later
stage) sends it after commit. A rolled-back command therefore never notifies anyone.
Payloads follow the journal rule: no names (``journal.service.check_payload``).
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.modules.common.enums import NotificationCategory, NotificationStatus
from app.modules.journal.service import check_payload
from app.modules.notifications.models import Notification

#: Telegram ``startapp`` parameter prefix for a quest occurrence (lib/deeplink.ts maps it).
QUEST_START_PREFIX = "q_"


def quest_deep_link(occurrence_id: int) -> str:
    return f"{QUEST_START_PREFIX}{occurrence_id}"


def enqueue(
    session: AsyncSession,
    *,
    recipient_id: int,
    type: str,
    category: NotificationCategory,
    entity_type: str | None,
    entity_id: int | None,
    payload: Mapping[str, Any],
    deep_link: str | None = None,
    send_after: datetime | None = None,
) -> Notification:
    """Add a pending notification to the session; it is written with the caller's
    transaction and sent by the dispatcher only after that commits."""
    check_payload(payload)
    notification = Notification(
        recipient_id=recipient_id,
        type=type,
        category=category,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=dict(payload),
        deep_link=deep_link,
        status=NotificationStatus.PENDING,
        send_after=send_after or clock.now(),
    )
    session.add(notification)
    return notification
