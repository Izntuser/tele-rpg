"""Inbox, preferences and write access (ARCHITECTURE §5 "notifications"), plus the API's
post-commit outbox hook (``dispatch_after_commit``, mounted on every /api route in
``app/main.py``)."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import ValidationError

from app.bot.dispatcher import get_bot
from app.core.deps import CurrentUser, SessionDep
from app.modules.common.validation import MAX_BIGINT, IdPath
from app.modules.notifications import dispatcher, service
from app.modules.notifications.schemas import (
    InboxOut,
    NotificationOut,
    PreferencesOut,
    PreferencesUpdate,
    ReadAllOut,
    UnreadCountOut,
    WriteAccessIn,
)

router = APIRouter(tags=["notifications"])


async def dispatch_after_commit(session: SessionDep) -> AsyncIterator[None]:
    """Request dependency: once the route has returned, send the notifications the request
    committed (a session event records their ids). A failed request skips this; the
    scheduler sweep sends them within 30 s."""
    dispatcher.track_session(session)
    yield
    committed = dispatcher.take_committed(session)
    if committed:
        await dispatcher.dispatch(session, get_bot(), committed)


@router.get("/notifications", response_model=InboxOut)
async def list_notifications(
    user: CurrentUser,
    session: SessionDep,
    cursor: Annotated[int | None, Query(gt=0, le=MAX_BIGINT)] = None,
    limit: Annotated[int, Query(ge=1, le=service.INBOX_PAGE_MAX)] = service.INBOX_PAGE_DEFAULT,
) -> InboxOut:
    """My inbox, newest first; pass ``next_cursor`` back as ``cursor`` for older items."""
    return await service.list_inbox(session, user, cursor=cursor, limit=limit)


@router.get("/notifications/unread-count", response_model=UnreadCountOut)
async def unread_notifications(user: CurrentUser, session: SessionDep) -> UnreadCountOut:
    """The header bell's badge."""
    return UnreadCountOut(count=await service.unread_count(session, user))


@router.post("/notifications/read-all", response_model=ReadAllOut)
async def read_all_notifications(user: CurrentUser, session: SessionDep) -> ReadAllOut:
    return ReadAllOut(updated=await service.mark_all_read(session, user))


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
async def read_notification(
    notification_id: IdPath, user: CurrentUser, session: SessionDep
) -> NotificationOut:
    """Mark one of my notifications read; someone else's answers 404."""
    try:
        return await service.mark_read(session, user, notification_id)
    except service.NotificationNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found") from None


@router.get("/notifications/preferences", response_model=PreferencesOut)
async def get_preferences(user: CurrentUser) -> PreferencesOut:
    return service.preferences_out(user)


@router.patch("/notifications/preferences", response_model=PreferencesOut)
async def patch_preferences(
    data: PreferencesUpdate, user: CurrentUser, session: SessionDep
) -> PreferencesOut:
    """Categories, quiet hours (both bounds null = off) and the daily summary."""
    try:
        return await service.update_preferences(session, user, data)
    except ValidationError as exc:
        await session.rollback()
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            exc.errors(include_input=False, include_context=False),
        ) from None


@router.post("/notifications/write-access", response_model=PreferencesOut)
async def write_access(
    data: WriteAccessIn, user: CurrentUser, session: SessionDep
) -> PreferencesOut:
    """Record the result of Telegram ``requestWriteAccess`` (``can_message``)."""
    return await service.set_write_access(session, user, data.allowed)
