"""Adventure Journal (ARCHITECTURE §5 ``GET /journal``): my events or my partnership's shared
events, newest first, keyset-paginated."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.core.deps import CurrentUser, SessionDep
from app.modules.common.validation import MAX_BIGINT
from app.modules.journal import service
from app.modules.journal.service import JournalPage, Scope

router = APIRouter(tags=["journal"])


@router.get("/journal", response_model=JournalPage)
async def list_journal(
    user: CurrentUser,
    session: SessionDep,
    scope: Scope = "me",
    cursor: Annotated[int | None, Query(gt=0, le=MAX_BIGINT)] = None,
    limit: Annotated[int, Query(ge=1, le=service.JOURNAL_PAGE_MAX)] = service.JOURNAL_PAGE_DEFAULT,
) -> JournalPage:
    """``scope=me``: everything I recorded (private included). ``scope=shared``: the shared
    events of my active partnership by either of us (empty without one). Pass ``next_cursor``
    back as ``cursor`` for older events."""
    return await service.list_events(session, user, scope=scope, cursor=cursor, limit=limit)
