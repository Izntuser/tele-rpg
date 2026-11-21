from datetime import UTC, date, datetime, timedelta, timezone
from types import ModuleType

import pytest

from app.core import clock
from tests.conftest import FROZEN_AT


def test_now_is_aware_utc_when_not_frozen() -> None:
    assert not clock.is_frozen()
    now = clock.now()
    assert now.tzinfo is UTC
    assert abs(datetime.now(UTC) - now) < timedelta(seconds=5)


def test_frozen_clock_fixture(frozen_clock: ModuleType) -> None:
    assert clock.now() == FROZEN_AT
    assert clock.now() == clock.now()
    frozen_clock.advance(timedelta(hours=13))
    assert clock.now() == FROZEN_AT + timedelta(hours=13)
    frozen_clock.freeze(datetime(2026, 3, 29, 0, 30, tzinfo=timezone(timedelta(hours=2))))
    assert clock.now() == datetime(2026, 3, 28, 22, 30, tzinfo=UTC)
    assert clock.now().tzinfo is UTC


def test_frozen_clock_is_released_after_the_test() -> None:
    assert not clock.is_frozen()


def test_today_in_uses_the_users_timezone(frozen_clock: ModuleType) -> None:
    frozen_clock.freeze(datetime(2026, 1, 15, 22, 30, tzinfo=UTC))
    assert clock.today_in("UTC") == date(2026, 1, 15)
    assert clock.today_in("Europe/Kyiv") == date(2026, 1, 16)
    assert clock.today_in("Pacific/Kiritimati") == date(2026, 1, 16)
    assert clock.today_in("Etc/GMT+12") == date(2026, 1, 15)


def test_freeze_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError):
        clock.freeze(datetime(2026, 1, 1))
    assert not clock.is_frozen()


def test_advance_requires_frozen_clock() -> None:
    with pytest.raises(RuntimeError):
        clock.advance(timedelta(seconds=1))
