"""Notification outbox writes, preferences, quiet hours and the inbox (ARCHITECTURE §3
"Notifications").

``enqueue`` only adds a ``pending`` row to the caller's transaction; the dispatcher
(``notifications/dispatcher.py``) sends it after commit. A rolled-back command therefore never
notifies anyone. Payloads follow the journal rule: no names (``journal.service.check_payload``).

Deep links are Telegram ``startapp`` values that the client maps to a route
(``frontend/src/lib/deeplink.ts``): ``q_<occurrence>``, ``qt_<template>`` (a recurring offer has
no occurrence yet), ``r_<purchase>`` (the buyer's voucher), ``rq_<purchase>`` (the provider's
request queue), ``rw_<reward>`` (the shop) and ``p_<partnership>`` (the companion page).
"""

from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.modules.common.enums import NotificationCategory, NotificationStatus
from app.modules.journal.service import check_payload
from app.modules.notifications.models import Notification
from app.modules.notifications.schemas import (
    InboxOut,
    NotificationOut,
    NotificationPrefs,
    PreferencesOut,
    PreferencesUpdate,
)
from app.modules.users.models import User

#: Telegram ``startapp`` parameter prefix for a quest occurrence (lib/deeplink.ts maps it).
QUEST_START_PREFIX = "q_"
TEMPLATE_START_PREFIX = "qt_"
VOUCHER_START_PREFIX = "r_"
REQUESTS_START_PREFIX = "rq_"
REWARD_START_PREFIX = "rw_"
PARTNERSHIP_START_PREFIX = "p_"

_DEFAULT_PREFIX_BY_ENTITY = {
    "quest_occurrence": QUEST_START_PREFIX,
    "quest_template": TEMPLATE_START_PREFIX,
    "reward_purchase": VOUCHER_START_PREFIX,
    "reward": REWARD_START_PREFIX,
    "partnership": PARTNERSHIP_START_PREFIX,
}

INBOX_PAGE_DEFAULT = 30
INBOX_PAGE_MAX = 100


class NotificationNotFoundError(LookupError):
    """No such notification for this recipient."""


def quest_deep_link(occurrence_id: int) -> str:
    return f"{QUEST_START_PREFIX}{occurrence_id}"


def voucher_deep_link(purchase_id: int, *, provider: bool) -> str:
    """The buyer opens the voucher in their inventory, the provider the request queue."""
    return f"{REQUESTS_START_PREFIX if provider else VOUCHER_START_PREFIX}{purchase_id}"


def default_deep_link(entity_type: str | None, entity_id: int | None) -> str | None:
    prefix = _DEFAULT_PREFIX_BY_ENTITY.get(entity_type or "")
    if prefix is None or entity_id is None:
        return None
    return f"{prefix}{entity_id}"


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
    transaction and sent by the dispatcher only after that commits. Without an explicit
    ``deep_link`` the entity decides it (``default_deep_link``)."""
    check_payload(payload)
    notification = Notification(
        recipient_id=recipient_id,
        type=type,
        category=category,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=dict(payload),
        deep_link=deep_link or default_deep_link(entity_type, entity_id),
        status=NotificationStatus.PENDING,
        send_after=send_after or clock.now(),
    )
    session.add(notification)
    return notification


# --- preferences -----------------------------------------------------------------------------


def prefs_of(user: User) -> NotificationPrefs:
    """The user's effective preferences; anything unreadable falls back to the defaults."""
    stored = user.notification_prefs if isinstance(user.notification_prefs, dict) else {}
    try:
        return NotificationPrefs.model_validate(stored)
    except ValidationError:
        return NotificationPrefs()


def preferences_out(user: User) -> PreferencesOut:
    return PreferencesOut(**prefs_of(user).model_dump(), can_message=user.can_message)


async def update_preferences(
    session: AsyncSession, user: User, data: PreferencesUpdate
) -> PreferencesOut:
    current = prefs_of(user).model_dump(mode="json")
    fields = data.model_fields_set
    if data.categories is not None:
        current["categories"] = {
            **current["categories"],
            **{k.value: v for k, v in data.categories.items()},
        }
    for name in ("quiet_hours_start", "quiet_hours_end"):
        if name in fields:
            current[name] = getattr(data, name)
    if data.daily_summary is not None:
        current["daily_summary"] = data.daily_summary
    prefs = NotificationPrefs.model_validate(current)  # raises when only one bound is cleared
    user.notification_prefs = prefs.model_dump(mode="json")
    await session.commit()
    return preferences_out(user)


async def set_write_access(session: AsyncSession, user: User, allowed: bool) -> PreferencesOut:
    user.can_message = allowed
    await session.commit()
    return preferences_out(user)


# --- quiet hours -----------------------------------------------------------------------------


def zone_of(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _parse_clock(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def quiet_until(
    now: datetime, timezone: str | None, start: str | None, end: str | None
) -> datetime | None:
    """When ``now`` falls inside the quiet hours ``[start, end)`` (wall-clock "HH:MM" in
    ``timezone``, possibly wrapping past midnight), the UTC instant they end; else None.

    Equal bounds or a missing bound mean no quiet hours. An end time that does not exist on
    that day (a DST gap) resolves to the first instant after the gap.
    """
    if start is None or end is None or start == end:
        return None
    zone = zone_of(timezone)
    local = now.astimezone(zone)
    wall = local.time().replace(tzinfo=None)
    start_t, end_t = _parse_clock(start), _parse_clock(end)
    end_day: date
    if start_t < end_t:
        if not (start_t <= wall < end_t):
            return None
        end_day = local.date()
    elif wall >= start_t:
        end_day = local.date() + timedelta(days=1)
    elif wall < end_t:
        end_day = local.date()
    else:
        return None
    until = datetime.combine(end_day, end_t, tzinfo=zone).astimezone(UTC)
    if until <= now:  # pragma: no cover - only reachable through DST folds at the boundary
        return None
    return until


def is_quiet(now: datetime, user: User, prefs: NotificationPrefs | None = None) -> bool:
    prefs = prefs or prefs_of(user)
    return (
        quiet_until(now, user.timezone, prefs.quiet_hours_start, prefs.quiet_hours_end) is not None
    )


# --- inbox -----------------------------------------------------------------------------------


async def unread_count(session: AsyncSession, user: User) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.recipient_id == user.id, Notification.read_at.is_(None))
    )
    return int(count or 0)


async def list_inbox(
    session: AsyncSession, user: User, *, cursor: int | None, limit: int = INBOX_PAGE_DEFAULT
) -> InboxOut:
    """Newest first; ``cursor`` is the last id of the previous page (older rows follow)."""
    limit = max(1, min(limit, INBOX_PAGE_MAX))
    query = select(Notification).where(Notification.recipient_id == user.id)
    if cursor is not None:
        query = query.where(Notification.id < cursor)
    rows = list(await session.scalars(query.order_by(Notification.id.desc()).limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    return InboxOut(
        items=[NotificationOut.model_validate(row) for row in rows],
        next_cursor=rows[-1].id if more and rows else None,
        unread_count=await unread_count(session, user),
    )


async def mark_read(session: AsyncSession, user: User, notification_id: int) -> NotificationOut:
    row = await session.scalar(
        select(Notification).where(
            Notification.id == notification_id, Notification.recipient_id == user.id
        )
    )
    if row is None:
        raise NotificationNotFoundError
    if row.read_at is None:
        row.read_at = clock.now()
        await session.commit()
    return NotificationOut.model_validate(row)


async def mark_all_read(session: AsyncSession, user: User) -> int:
    result = await session.execute(
        update(Notification)
        .where(Notification.recipient_id == user.id, Notification.read_at.is_(None))
        .values(read_at=clock.now())
    )
    await session.commit()
    return int(getattr(result, "rowcount", 0) or 0)
