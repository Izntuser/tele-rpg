"""Outbox dispatcher: sends committed ``pending`` notifications through the bot (ARCHITECTURE
§3 "Notifications", DECISIONS 20).

Two callers: the API right after a request (``track_session`` records the ids of the
notifications the request committed, then ``dispatch`` sends just those) and the scheduler
sweep every 30 s (``dispatch`` with no ids). Each row is claimed in its own short
transaction with ``FOR UPDATE SKIP LOCKED`` and re-checked under the lock, so the two can
never send one row twice; the row stays locked while the message goes out and its outcome
is committed right after.

For each due row (``send_after <= now``):

- the recipient is deleted -> the row is deleted (its payload must not outlive the account);
- the category is turned off, or ``can_message`` is false -> ``skipped``;
- the recipient is inside quiet hours -> reminders and summaries are ``skipped`` (they are
  only useful on time), everything else is deferred: ``send_after`` = end of quiet hours;
- otherwise the bot sends the localized text with an inline button that opens the Mini App at
  the row's deep link. Success -> ``sent``. A user who blocked the bot -> ``skipped`` and
  ``can_message`` cleared. Flood control -> retried after ``retry_after``. Any other failure
  -> retried with backoff until ``MAX_ATTEMPTS``, then ``failed``.
"""

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from sqlalchemy import delete, event, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.bot import i18n
from app.bot.dispatcher import notification_button
from app.core import clock
from app.modules.common.enums import NotificationCategory, NotificationStatus
from app.modules.notifications.models import Notification
from app.modules.notifications.service import prefs_of, quiet_until
from app.modules.users.models import User

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
#: Delay before retry n (1-based); the last value repeats.
RETRY_BACKOFF = (
    timedelta(seconds=30),
    timedelta(minutes=2),
    timedelta(minutes=10),
    timedelta(hours=1),
)
SWEEP_BATCH = 100
#: Categories that are useless late: skipped instead of deferred inside quiet hours.
ON_TIME_ONLY = frozenset({NotificationCategory.REMINDERS, NotificationCategory.SUMMARY})

#: ``session.info`` keys of the API post-commit hook.
TRACK_KEY = "notifications.track"
FLUSHED_KEY = "notifications.flushed"
COMMITTED_KEY = "notifications.committed"


@dataclass(slots=True)
class DispatchResult:
    sent: list[int] = field(default_factory=list)
    skipped: list[int] = field(default_factory=list)
    deferred: list[int] = field(default_factory=list)
    retried: list[int] = field(default_factory=list)
    failed: list[int] = field(default_factory=list)
    deleted: int = 0


# --- API post-commit hook --------------------------------------------------------------------


@event.listens_for(Session, "after_flush")
def _collect_flushed(session: Session, _flush_context: Any) -> None:
    """A tracked session remembers the ids of the notifications it inserts..."""
    if not session.info.get(TRACK_KEY):
        return
    flushed = session.info.setdefault(FLUSHED_KEY, set())
    for obj in session.new:
        if isinstance(obj, Notification) and obj.id is not None:
            flushed.add(obj.id)


@event.listens_for(Session, "after_commit")
def _collect_committed(session: Session) -> None:
    """...and keeps them once they are committed..."""
    flushed = session.info.pop(FLUSHED_KEY, None)
    if flushed:
        session.info.setdefault(COMMITTED_KEY, set()).update(flushed)


@event.listens_for(Session, "after_soft_rollback")
def _forget_rolled_back(session: Session, _previous: Any) -> None:
    """...or forgets them when they are rolled back."""
    session.info.pop(FLUSHED_KEY, None)


def track_session(session: AsyncSession) -> None:
    session.sync_session.info[TRACK_KEY] = True


def take_committed(session: AsyncSession) -> set[int]:
    """Ids of the notifications this tracked session has committed (and forget them)."""
    committed: set[int] = session.sync_session.info.pop(COMMITTED_KEY, set())
    return committed


async def _end_transaction(session: AsyncSession) -> None:
    """Close the caller's transaction before claiming rows. Services commit their own work,
    so what is left is a read-only transaction (committed, which keeps the caller's loaded
    objects usable); uncommitted notification inserts mean a half-done command, which is
    rolled back."""
    if session.sync_session.info.get(FLUSHED_KEY) or session.new or session.dirty:
        await session.rollback()
    elif session.in_transaction():
        await session.commit()


# --- rendering -------------------------------------------------------------------------------


def message_text(notification: Notification, locale: str | None) -> str:
    key = f"notification.types.{notification.type}"
    if not i18n.has(key):
        return i18n.text(locale, "notification.generic")
    return i18n.render(locale, key, notification.payload)


def retry_delay(attempts: int) -> timedelta:
    return RETRY_BACKOFF[min(max(attempts, 1), len(RETRY_BACKOFF)) - 1]


# --- dispatch --------------------------------------------------------------------------------


async def _purge_deleted_recipients(session: AsyncSession, ids: Iterable[int] | None) -> int:
    stmt = delete(Notification).where(
        Notification.status == NotificationStatus.PENDING,
        Notification.recipient_id.in_(select(User.id).where(User.deleted_at.is_not(None))),
    )
    if ids is not None:
        stmt = stmt.where(Notification.id.in_(list(ids)))
    result = await session.execute(stmt)
    await session.commit()
    return int(getattr(result, "rowcount", 0) or 0)


async def _due_ids(session: AsyncSession, now: datetime, ids: Iterable[int] | None) -> list[int]:
    query = (
        select(Notification.id)
        .where(Notification.status == NotificationStatus.PENDING, Notification.send_after <= now)
        .order_by(Notification.id)
        .limit(SWEEP_BATCH)
    )
    if ids is not None:
        query = query.where(Notification.id.in_(list(ids)))
    found = list(await session.scalars(query))
    await session.commit()  # read-only
    return found


async def _block_user(session: AsyncSession, user_id: int) -> None:
    """The user blocked the bot: stop trying until they allow messages again. Its own
    transaction, after the row's, so no notification lock is held while the user row is."""
    await session.execute(update(User).where(User.id == user_id).values(can_message=False))
    await session.commit()


async def _dispatch_one(
    session: AsyncSession, bot: Bot, notification_id: int, result: DispatchResult
) -> None:
    now = clock.now()
    row = await session.scalar(
        select(Notification)
        .where(
            Notification.id == notification_id,
            Notification.status == NotificationStatus.PENDING,
            Notification.send_after <= now,
        )
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    if row is None:  # sent by the other dispatcher, deferred, or rolled back
        await session.commit()  # read-only
        return
    user = await session.scalar(
        select(User).where(User.id == row.recipient_id).execution_options(populate_existing=True)
    )
    if user is None or user.deleted_at is not None:
        await session.delete(row)
        await session.commit()
        result.deleted += 1
        return
    prefs = prefs_of(user)
    if not prefs.category_enabled(row.category) or not user.can_message:
        row.status = NotificationStatus.SKIPPED
        await session.commit()
        result.skipped.append(row.id)
        return
    quiet_end = quiet_until(now, user.timezone, prefs.quiet_hours_start, prefs.quiet_hours_end)
    if quiet_end is not None:
        if row.category in ON_TIME_ONLY:
            row.status = NotificationStatus.SKIPPED
            result.skipped.append(row.id)
        else:
            row.send_after = quiet_end
            result.deferred.append(row.id)
        await session.commit()
        return

    locale = user.locale.value
    blocked = False
    row.attempts += 1
    try:
        await bot.send_message(
            chat_id=user.tg_user_id,
            text=message_text(row, locale),
            reply_markup=notification_button(i18n.text(locale, "notification.open"), row.deep_link),
        )
    except TelegramForbiddenError:
        row.status = NotificationStatus.SKIPPED
        blocked = True
        result.skipped.append(row.id)
    except TelegramRetryAfter as exc:
        row.attempts -= 1  # flood control is not the message's fault
        row.send_after = clock.now() + timedelta(seconds=max(exc.retry_after, 1))
        result.retried.append(row.id)
    except (TelegramAPIError, OSError, TimeoutError) as exc:
        log.warning("notification %s send failed (attempt %s): %s", row.id, row.attempts, exc)
        if row.attempts >= MAX_ATTEMPTS:
            row.status = NotificationStatus.FAILED
            result.failed.append(row.id)
        else:
            row.send_after = clock.now() + retry_delay(row.attempts)
            result.retried.append(row.id)
    else:
        row.status = NotificationStatus.SENT
        row.delivered_at = clock.now()
        result.sent.append(row.id)
    await session.commit()
    if blocked:
        await _block_user(session, user.id)


async def dispatch(
    session: AsyncSession, bot: Bot, ids: Sequence[int] | set[int] | None = None
) -> DispatchResult:
    """Send what is due: only ``ids`` (the API after a commit) or the oldest due rows (the
    sweep). The caller's open transaction is closed first (``_end_transaction``)."""
    await _end_transaction(session)
    result = DispatchResult()
    id_list = sorted(ids) if ids is not None else None
    if id_list is not None and not id_list:
        return result
    result.deleted += await _purge_deleted_recipients(session, id_list)
    for notification_id in await _due_ids(session, clock.now(), id_list):
        try:
            await _dispatch_one(session, bot, notification_id, result)
        except Exception:
            await session.rollback()
            log.exception("dispatching notification %s failed", notification_id)
    return result
