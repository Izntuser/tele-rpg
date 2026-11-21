"""The single source of "now" for services and jobs.

Call ``clock.now()`` / ``clock.today_in(tz)`` (module attribute access, never
``from app.core.clock import now``-and-cache) so tests can freeze time with ``freeze``.
Database ``server_default=now()`` values are *not* frozen; services that need testable
timestamps must pass ``clock.now()`` explicitly.
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

_frozen: datetime | None = None


def now() -> datetime:
    """Current time, timezone-aware UTC."""
    return _frozen if _frozen is not None else datetime.now(UTC)


def today_in(tz: str) -> date:
    """Today's calendar date in the IANA timezone ``tz``."""
    return now().astimezone(ZoneInfo(tz)).date()


def freeze(at: datetime) -> None:
    """Pin ``now()`` to ``at`` (must be timezone-aware; stored as UTC)."""
    global _frozen
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("clock.freeze() needs a timezone-aware datetime")
    _frozen = at.astimezone(UTC)


def advance(delta: timedelta) -> None:
    """Move a frozen clock forward (or back, with a negative delta)."""
    global _frozen
    if _frozen is None:
        raise RuntimeError("clock is not frozen")
    _frozen = _frozen + delta


def unfreeze() -> None:
    global _frozen
    _frozen = None


def is_frozen() -> bool:
    return _frozen is not None
