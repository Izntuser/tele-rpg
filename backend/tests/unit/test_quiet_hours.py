"""Quiet hours, the summary window, preferences parsing, retry backoff and bot texts: pure
functions, no database."""

from datetime import UTC, datetime, timedelta

import pytest

from app.bot import i18n
from app.jobs.notification_jobs import summary_send_at
from app.modules.common.enums import NotificationCategory
from app.modules.notifications.dispatcher import MAX_ATTEMPTS, RETRY_BACKOFF, retry_delay
from app.modules.notifications.schemas import NotificationPrefs
from app.modules.notifications.service import default_deep_link, quiet_until, voucher_deep_link


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        # 23:00-08:00 UTC wraps past midnight.
        (utc(2026, 1, 15, 22, 59), None),
        (utc(2026, 1, 15, 23, 0), utc(2026, 1, 16, 8, 0)),
        (utc(2026, 1, 15, 23, 59), utc(2026, 1, 16, 8, 0)),
        (utc(2026, 1, 16, 0, 0), utc(2026, 1, 16, 8, 0)),
        (utc(2026, 1, 16, 7, 59), utc(2026, 1, 16, 8, 0)),
        (utc(2026, 1, 16, 8, 0), None),
        (utc(2026, 1, 16, 12, 0), None),
    ],
)
def test_wrapping_quiet_hours_in_utc(now: datetime, expected: datetime | None) -> None:
    assert quiet_until(now, "UTC", "23:00", "08:00") == expected


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (utc(2026, 1, 15, 12, 59), None),
        (utc(2026, 1, 15, 13, 0), utc(2026, 1, 15, 15, 30)),
        (utc(2026, 1, 15, 15, 29), utc(2026, 1, 15, 15, 30)),
        (utc(2026, 1, 15, 15, 30), None),
    ],
)
def test_same_day_quiet_hours(now: datetime, expected: datetime | None) -> None:
    assert quiet_until(now, "UTC", "13:00", "15:30") == expected


def test_quiet_hours_use_the_users_timezone() -> None:
    # Kyiv is UTC+2 in January: 21:30 UTC is 23:30 local, quiet until 08:00 local = 06:00 UTC.
    assert quiet_until(utc(2026, 1, 15, 21, 30), "Europe/Kyiv", "23:00", "08:00") == utc(
        2026, 1, 16, 6, 0
    )
    # 20:30 UTC is 22:30 in Kyiv: not quiet yet, although it would be in UTC+3.
    assert quiet_until(utc(2026, 1, 15, 20, 30), "Europe/Kyiv", "22:45", "08:00") is None
    # New York (UTC-5): 03:00 UTC is 22:00 the previous local day.
    assert quiet_until(utc(2026, 1, 16, 3, 0), "America/New_York", "21:00", "07:00") == utc(
        2026, 1, 16, 12, 0
    )


def test_quiet_hours_across_a_dst_change() -> None:
    # Kyiv springs forward on 2026-03-29 (03:00 -> 04:00, UTC+2 -> UTC+3). Quiet 23:00-08:00
    # starting the evening before ends at 08:00 summer time = 05:00 UTC.
    assert quiet_until(utc(2026, 3, 28, 22, 0), "Europe/Kyiv", "23:00", "08:00") == utc(
        2026, 3, 29, 5, 0
    )
    # An end inside the skipped hour (03:30) resolves to a real instant after now.
    until = quiet_until(utc(2026, 3, 28, 23, 0), "Europe/Kyiv", "00:00", "03:30")
    assert until is not None and until > utc(2026, 3, 28, 23, 0)
    assert until <= utc(2026, 3, 29, 1, 30)
    # Autumn: back from UTC+3 to UTC+2 on 2026-10-25; 08:00 local is 06:00 UTC.
    assert quiet_until(utc(2026, 10, 24, 21, 0), "Europe/Kyiv", "23:00", "08:00") == utc(
        2026, 10, 25, 6, 0
    )


@pytest.mark.parametrize(
    ("start", "end"), [(None, None), ("23:00", None), (None, "08:00"), ("08:00", "08:00")]
)
def test_missing_or_equal_bounds_mean_no_quiet_hours(start: str | None, end: str | None) -> None:
    assert quiet_until(utc(2026, 1, 16, 2, 0), "UTC", start, end) is None


def test_unknown_timezone_falls_back_to_utc() -> None:
    assert quiet_until(utc(2026, 1, 16, 2, 0), "Mars/Olympus", "23:00", "08:00") == utc(
        2026, 1, 16, 8, 0
    )


def test_summary_window_is_nine_to_noon_local() -> None:
    # Kyiv (UTC+2): 07:00 UTC = 09:00 local.
    assert summary_send_at(utc(2026, 1, 15, 6, 59), "Europe/Kyiv") is None
    assert summary_send_at(utc(2026, 1, 15, 7, 0), "Europe/Kyiv") == utc(2026, 1, 15, 7, 0)
    assert summary_send_at(utc(2026, 1, 15, 9, 59), "Europe/Kyiv") == utc(2026, 1, 15, 7, 0)
    assert summary_send_at(utc(2026, 1, 15, 10, 0), "Europe/Kyiv") is None
    # The send time is the same all morning, so each local day yields one row.
    assert summary_send_at(utc(2026, 1, 15, 9, 5), "UTC") == summary_send_at(
        utc(2026, 1, 15, 11, 55), "UTC"
    )


def test_prefs_default_and_merge() -> None:
    prefs = NotificationPrefs.model_validate({})
    assert all(prefs.categories[c] for c in NotificationCategory)
    assert (prefs.quiet_hours_start, prefs.quiet_hours_end) == ("23:00", "08:00")
    assert prefs.daily_summary is True
    partial = NotificationPrefs.model_validate({"categories": {"rewards": False}})
    assert partial.category_enabled(NotificationCategory.REWARDS) is False
    assert partial.category_enabled(NotificationCategory.QUESTS) is True
    off = NotificationPrefs.model_validate({"quiet_hours_start": None, "quiet_hours_end": None})
    assert off.quiet_hours_start is None


@pytest.mark.parametrize(
    "stored",
    [
        {"quiet_hours_start": "24:00", "quiet_hours_end": "08:00"},
        {"quiet_hours_start": "7:00", "quiet_hours_end": "08:00"},
        {"quiet_hours_start": None, "quiet_hours_end": "08:00"},
        {"categories": {"spam": True}},
    ],
)
def test_prefs_reject_bad_values(stored: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        NotificationPrefs.model_validate(stored)


def test_retry_backoff_grows_and_is_capped() -> None:
    delays = [retry_delay(n) for n in range(1, MAX_ATTEMPTS + 2)]
    assert delays[0] == timedelta(seconds=30)
    assert delays == sorted(delays)
    assert delays[-1] == RETRY_BACKOFF[-1]


def test_deep_links_by_entity() -> None:
    assert default_deep_link("quest_occurrence", 5) == "q_5"
    assert default_deep_link("quest_template", 5) == "qt_5"
    assert default_deep_link("reward", 5) == "rw_5"
    assert default_deep_link("reward_purchase", 5) == "r_5"
    assert default_deep_link("partnership", 5) == "p_5"
    assert default_deep_link(None, None) is None
    assert default_deep_link("quest_occurrence", None) is None
    assert voucher_deep_link(9, provider=False) == "r_9"
    assert voucher_deep_link(9, provider=True) == "rq_9"


def test_bot_catalogs_have_the_same_keys() -> None:
    en = i18n.flat_keys(i18n.catalog("en"))
    uk = i18n.flat_keys(i18n.catalog("uk"))
    assert en == uk
    assert "notification.types.quest_offered" in en


def test_render_fills_scalars_only_and_blanks_missing_fields() -> None:
    text = i18n.render("en", "notification.types.quest_confirmed", {"title": "Run", "gold": 5})
    assert text == "Quest confirmed: Run. +5 Gold, + XP"
    # A payload can never reach attribute lookups or inject format fields.
    evil = i18n.render("en", "notification.types.quest_offered", {"title": "{gold.__class__}"})
    assert evil == "New quest offered: {gold.__class__} ( Gold)"
    assert i18n.render("uk", "start.open_app") == "Відкрити застосунок"
    assert i18n.text("de", "start.open_app") == "Open the app"
