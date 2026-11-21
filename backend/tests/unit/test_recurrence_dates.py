"""Occurrence dates with a frozen clock: the assignee's calendar day / ISO week, due_at at the
next local midnight, across the Europe/Kyiv vs UTC boundary, DST changes and extreme offsets."""

from datetime import UTC, date, datetime
from types import ModuleType

import pytest

from app.core import clock
from app.modules.common.enums import Recurrence
from app.modules.quests.occurrences import period_start, recurring_due_at


def at(y: int, mo: int, d: int, h: int = 0, mi: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


def scheduled(recurrence: Recurrence, tz: str) -> date:
    return period_start(recurrence, clock.today_in(tz))


def test_day_boundary_kyiv_vs_utc(frozen_clock: ModuleType) -> None:
    # 22:30 UTC on Jan 15 is already 00:30 on Jan 16 in Kyiv (UTC+2 in winter).
    clock.freeze(at(2026, 1, 15, 22, 30))
    assert scheduled(Recurrence.DAILY, "UTC") == date(2026, 1, 15)
    assert scheduled(Recurrence.DAILY, "Europe/Kyiv") == date(2026, 1, 16)
    # One minute before Kyiv midnight both agree again.
    clock.freeze(at(2026, 1, 15, 21, 59))
    assert scheduled(Recurrence.DAILY, "Europe/Kyiv") == date(2026, 1, 15)
    clock.freeze(at(2026, 1, 15, 22, 0))
    assert scheduled(Recurrence.DAILY, "Europe/Kyiv") == date(2026, 1, 16)


def test_summer_kyiv_offset_is_three_hours(frozen_clock: ModuleType) -> None:
    clock.freeze(at(2026, 7, 1, 20, 59))
    assert scheduled(Recurrence.DAILY, "Europe/Kyiv") == date(2026, 7, 1)
    clock.freeze(at(2026, 7, 1, 21, 0))
    assert scheduled(Recurrence.DAILY, "Europe/Kyiv") == date(2026, 7, 2)


@pytest.mark.parametrize(
    ("day", "expected_due"),
    [
        # Spring forward 2026-03-29: that Kyiv day has 23 hours; it ends 21:00Z (UTC+3).
        (date(2026, 3, 28), at(2026, 3, 28, 22)),
        (date(2026, 3, 29), at(2026, 3, 29, 21)),
        (date(2026, 3, 30), at(2026, 3, 30, 21)),
        # Fall back 2026-10-25: 25 hours, ends 22:00Z (UTC+2).
        (date(2026, 10, 24), at(2026, 10, 24, 21)),
        (date(2026, 10, 25), at(2026, 10, 25, 22)),
        (date(2026, 10, 26), at(2026, 10, 26, 22)),
    ],
)
def test_daily_due_at_across_dst(day: date, expected_due: datetime) -> None:
    assert recurring_due_at(Recurrence.DAILY, day, "Europe/Kyiv") == expected_due


def test_daily_due_at_is_next_local_midnight_in_utc() -> None:
    assert recurring_due_at(Recurrence.DAILY, date(2026, 1, 15), "UTC") == at(2026, 1, 16)
    assert recurring_due_at(Recurrence.DAILY, date(2026, 1, 15), "Europe/Kyiv") == at(
        2026, 1, 15, 22
    )
    assert recurring_due_at(Recurrence.ONCE, date(2026, 1, 15), "UTC") is None


def test_week_starts_on_monday() -> None:
    monday = date(2026, 1, 12)
    for offset in range(7):
        assert period_start(Recurrence.WEEKLY, date(2026, 1, 12 + offset)) == monday
    assert period_start(Recurrence.WEEKLY, date(2026, 1, 19)) == date(2026, 1, 19)
    # ISO weeks cross the year boundary: Thu 2026-01-01 belongs to the week of Mon 2025-12-29.
    assert period_start(Recurrence.WEEKLY, date(2026, 1, 1)) == date(2025, 12, 29)
    assert period_start(Recurrence.DAILY, date(2026, 1, 1)) == date(2026, 1, 1)


def test_week_boundary_depends_on_the_users_timezone(frozen_clock: ModuleType) -> None:
    # Sunday 23:30 UTC is Monday 01:30 in Kyiv: the new week has already begun there.
    clock.freeze(at(2026, 1, 18, 23, 30))
    assert scheduled(Recurrence.WEEKLY, "UTC") == date(2026, 1, 12)
    assert scheduled(Recurrence.WEEKLY, "Europe/Kyiv") == date(2026, 1, 19)


def test_weekly_due_at_across_the_dst_changes() -> None:
    # Week of Mon 2026-03-23 ends Mon 03-30 00:00 EEST = Sun 03-29 21:00Z (6 days 23 hours).
    assert recurring_due_at(Recurrence.WEEKLY, date(2026, 3, 23), "Europe/Kyiv") == at(
        2026, 3, 29, 21
    )
    # Week of Mon 2026-10-19 ends Mon 10-26 00:00 EET = Sun 10-25 22:00Z.
    assert recurring_due_at(Recurrence.WEEKLY, date(2026, 10, 19), "Europe/Kyiv") == at(
        2026, 10, 25, 22
    )


def test_utc_plus_14_and_utc_minus_12(frozen_clock: ModuleType) -> None:
    clock.freeze(at(2026, 1, 15, 12, 0))
    # Kiritimati (UTC+14) is two hours into Jan 16; Etc/GMT+12 (UTC-12) is at midnight Jan 15.
    assert scheduled(Recurrence.DAILY, "Pacific/Kiritimati") == date(2026, 1, 16)
    assert scheduled(Recurrence.DAILY, "Etc/GMT+12") == date(2026, 1, 15)
    clock.freeze(at(2026, 1, 15, 11, 59))
    assert scheduled(Recurrence.DAILY, "Etc/GMT+12") == date(2026, 1, 14)
    clock.freeze(at(2026, 1, 15, 9, 59))
    assert scheduled(Recurrence.DAILY, "Pacific/Kiritimati") == date(2026, 1, 15)
    clock.freeze(at(2026, 1, 15, 10, 0))
    assert scheduled(Recurrence.DAILY, "Pacific/Kiritimati") == date(2026, 1, 16)

    # Local midnight ending Jan 16 at UTC+14 is 10:00Z on Jan 16; ending Jan 15 at UTC-12 is
    # 12:00Z on Jan 16.
    assert recurring_due_at(Recurrence.DAILY, date(2026, 1, 16), "Pacific/Kiritimati") == at(
        2026, 1, 16, 10
    )
    assert recurring_due_at(Recurrence.DAILY, date(2026, 1, 15), "Etc/GMT+12") == at(
        2026, 1, 16, 12
    )
