"""The notification outbox: post-commit send from the API, the sweep, preferences, quiet hours,
can_message, retries, reminder / summary jobs and the inbox API. FakeBot records every send;
nothing reaches Telegram."""

import asyncio
from collections.abc import Iterator
from datetime import timedelta
from types import ModuleType
from typing import Any

import httpx
import pytest
from aiogram.exceptions import (
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.methods import SendMessage
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.dispatcher import set_bot
from app.bot.fake import FakeBot
from app.core import clock, ratelimit
from app.core.config import get_settings
from app.jobs import expire_occurrences, notification_jobs
from app.jobs.runner import DEFAULT_JOBS
from app.modules.common.enums import (
    Locale,
    NotificationCategory,
    NotificationStatus,
    QuestOccurrenceStatus,
)
from app.modules.notifications import dispatcher
from app.modules.notifications.models import Notification
from app.modules.notifications.service import enqueue
from app.modules.quests.models import QuestOccurrence
from app.modules.rewards.models import RewardPurchase
from app.modules.rewards.service import voucher_event
from app.modules.users.models import User
from tests import factories
from tests.integration.completion_support import active_quest, auth, ident, pair

pytestmark = pytest.mark.usefixtures("frozen_clock")


@pytest.fixture(autouse=True)
def _clean_limiters() -> None:
    ratelimit.reset_all()


@pytest.fixture
def bot() -> Iterator[FakeBot]:
    fake = FakeBot()
    set_bot(fake)
    try:
        yield fake
    finally:
        set_bot(None)


@pytest.fixture(autouse=True)
def _names(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "tg_bot_username", "telerpg_bot")
    monkeypatch.setattr(settings, "tg_app_short_name", "play")


def button_url(message: SendMessage) -> str | None:
    markup: Any = message.reply_markup
    button = markup.inline_keyboard[0][0]
    url: str | None = button.url
    return url


async def reachable_pair(session: AsyncSession, **player: Any) -> tuple[User, User, int]:
    gm, pl, partnership = await pair(session)
    for user in (gm, pl):
        user.can_message = True
    for key, value in player.items():
        setattr(pl, key, value)
    await session.commit()
    return gm, pl, partnership.id


async def note(session: AsyncSession, notification_id: int) -> Notification:
    row = await session.scalar(
        select(Notification)
        .where(Notification.id == notification_id)
        .execution_options(populate_existing=True)
    )
    assert row is not None
    return row


async def drain(session: AsyncSession, bot: FakeBot) -> None:
    """Send what earlier setup steps enqueued and forget those messages."""
    await dispatcher.dispatch(session, bot)
    bot.reset()


async def pending_note(
    session: AsyncSession,
    user: User,
    category: NotificationCategory = NotificationCategory.QUESTS,
    entity_id: int = 77,
) -> int:
    row = enqueue(
        session,
        recipient_id=user.id,
        type="quest_offered",
        category=category,
        entity_type="quest_occurrence",
        entity_id=entity_id,
        payload={"title": "Morning run", "gold": 40},
    )
    await session.commit()
    return row.id


# --- post-commit send ------------------------------------------------------------------------


async def test_api_sends_the_offer_right_after_commit_with_a_deep_link(
    client: httpx.AsyncClient, session: AsyncSession, bot: FakeBot
) -> None:
    gm, player, _ = await reachable_pair(session)
    response = await client.post(
        "/api/quests",
        headers=auth(gm),
        json={"title": "Morning run", "attribute": "physical", "gold": 40},
    )
    assert response.status_code == 201, response.text
    occurrence_id = response.json()["occurrence"]["id"]
    [message] = bot.messages
    assert message.chat_id == player.tg_user_id
    assert message.text == "New quest offered: Morning run (40 Gold)"
    assert button_url(message) == f"https://t.me/telerpg_bot/play?startapp=q_{occurrence_id}"
    row = await session.scalar(select(Notification).execution_options(populate_existing=True))
    assert row is not None
    assert row.status == NotificationStatus.SENT
    assert row.attempts == 1 and row.delivered_at == clock.now()


async def test_message_follows_the_recipients_locale(
    client: httpx.AsyncClient, session: AsyncSession, bot: FakeBot
) -> None:
    gm, _player, _ = await reachable_pair(session, locale=Locale.UK)
    response = await client.post(
        "/api/quests",
        headers=auth(gm),
        json={"title": "Біг", "attribute": "physical", "gold": 40},
    )
    assert response.status_code == 201
    [message] = bot.messages
    assert message.text == "Новий квест: Біг (40 золота)"
    markup: Any = message.reply_markup
    assert markup.inline_keyboard[0][0].text == "Відкрити"


async def test_a_failed_request_sends_nothing_and_leaves_no_row(
    client: httpx.AsyncClient, session: AsyncSession, bot: FakeBot
) -> None:
    gm, _player, _ = await reachable_pair(session)
    response = await client.post(
        "/api/quests", headers=auth(gm), json={"title": "", "attribute": "physical", "gold": 40}
    )
    assert response.status_code == 422
    assert bot.messages == []
    assert await session.scalar(select(func.count()).select_from(Notification)) == 0


async def test_rolled_back_transaction_leaves_no_notification(
    session: AsyncSession, bot: FakeBot
) -> None:
    _gm, player, _ = await reachable_pair(session)
    enqueue(
        session,
        recipient_id=player.id,
        type="quest_offered",
        category=NotificationCategory.QUESTS,
        entity_type=None,
        entity_id=None,
        payload={},
    )
    await session.flush()
    await session.rollback()
    result = await dispatcher.dispatch(session, bot)
    assert result.sent == [] and bot.messages == []
    assert await session.scalar(select(func.count()).select_from(Notification)) == 0


async def test_post_commit_hook_only_reports_committed_rows(session: AsyncSession) -> None:
    _gm, player, _ = await reachable_pair(session)
    dispatcher.track_session(session)
    rolled_back = await pending_note(session, player)  # committed
    enqueue(
        session,
        recipient_id=player.id,
        type="x",
        category=NotificationCategory.QUESTS,
        entity_type=None,
        entity_id=None,
        payload={},
    )
    await session.flush()
    await session.rollback()
    assert dispatcher.take_committed(session) == {rolled_back}
    assert dispatcher.take_committed(session) == set()


# --- rules -----------------------------------------------------------------------------------


async def test_disabled_category_is_skipped(session: AsyncSession, bot: FakeBot) -> None:
    _gm, player, _ = await reachable_pair(
        session, notification_prefs={"categories": {"quests": False}}
    )
    notification_id = await pending_note(session, player)
    result = await dispatcher.dispatch(session, bot)
    assert result.skipped == [notification_id]
    assert (await note(session, notification_id)).status == NotificationStatus.SKIPPED
    assert bot.messages == []


async def test_without_can_message_nothing_is_sent(session: AsyncSession, bot: FakeBot) -> None:
    _gm, player, _ = await reachable_pair(session, can_message=False)
    notification_id = await pending_note(session, player)
    await dispatcher.dispatch(session, bot)
    assert (await note(session, notification_id)).status == NotificationStatus.SKIPPED
    assert bot.messages == []


async def test_quiet_hours_defer_until_they_end_then_the_sweep_sends(
    session: AsyncSession, bot: FakeBot, frozen_clock: ModuleType
) -> None:
    # 12:00 UTC is 14:00 in Kyiv; quiet 13:00-15:00 local ends at 13:00 UTC.
    _gm, player, _ = await reachable_pair(
        session,
        timezone="Europe/Kyiv",
        notification_prefs={"quiet_hours_start": "13:00", "quiet_hours_end": "15:00"},
    )
    notification_id = await pending_note(session, player)
    result = await dispatcher.dispatch(session, bot)
    assert result.deferred == [notification_id]
    row = await note(session, notification_id)
    assert row.status == NotificationStatus.PENDING
    assert row.send_after == clock.now() + timedelta(hours=1)
    assert bot.messages == []
    # Not due yet: a sweep before the end sends nothing.
    frozen_clock.advance(timedelta(minutes=59))
    assert (await dispatcher.dispatch(session, bot)).sent == []
    frozen_clock.advance(timedelta(minutes=1))
    assert (await dispatcher.dispatch(session, bot)).sent == [notification_id]
    assert len(bot.messages) == 1


async def test_reminders_and_summaries_are_skipped_inside_quiet_hours(
    session: AsyncSession, bot: FakeBot
) -> None:
    _gm, player, _ = await reachable_pair(
        session, notification_prefs={"quiet_hours_start": "11:00", "quiet_hours_end": "13:00"}
    )
    reminder = await pending_note(session, player, NotificationCategory.REMINDERS)
    summary = await pending_note(session, player, NotificationCategory.SUMMARY, entity_id=78)
    result = await dispatcher.dispatch(session, bot)
    assert sorted(result.skipped) == sorted([reminder, summary])
    assert bot.messages == []


async def test_failures_retry_with_backoff_up_to_the_attempts_cap(
    session: AsyncSession, bot: FakeBot, frozen_clock: ModuleType
) -> None:
    _gm, player, _ = await reachable_pair(session)
    notification_id = await pending_note(session, player)
    method = SendMessage(chat_id=1, text="x")
    for attempt in range(1, dispatcher.MAX_ATTEMPTS + 1):
        bot.fail_next(TelegramNetworkError(method=method, message="boom"))
        await dispatcher.dispatch(session, bot)
        row = await note(session, notification_id)
        assert row.attempts == attempt
        if attempt < dispatcher.MAX_ATTEMPTS:
            assert row.status == NotificationStatus.PENDING
            assert row.send_after == clock.now() + dispatcher.retry_delay(attempt)
            # Not retried before its backoff is over.
            assert (await dispatcher.dispatch(session, bot)).retried == []
            frozen_clock.advance(dispatcher.retry_delay(attempt))
    assert row.status == NotificationStatus.FAILED
    assert bot.messages == []
    frozen_clock.advance(timedelta(days=1))
    assert (await dispatcher.dispatch(session, bot)).sent == []


async def test_a_retry_after_a_failure_succeeds(
    session: AsyncSession, bot: FakeBot, frozen_clock: ModuleType
) -> None:
    _gm, player, _ = await reachable_pair(session)
    notification_id = await pending_note(session, player)
    bot.fail_next(TelegramNetworkError(method=SendMessage(chat_id=1, text="x"), message="boom"))
    assert (await dispatcher.dispatch(session, bot)).retried == [notification_id]
    frozen_clock.advance(dispatcher.retry_delay(1))
    assert (await dispatcher.dispatch(session, bot)).sent == [notification_id]
    row = await note(session, notification_id)
    assert row.status == NotificationStatus.SENT and row.attempts == 2


async def test_flood_control_waits_without_spending_an_attempt(
    session: AsyncSession, bot: FakeBot
) -> None:
    _gm, player, _ = await reachable_pair(session)
    notification_id = await pending_note(session, player)
    method = SendMessage(chat_id=1, text="x")
    bot.fail_next(TelegramRetryAfter(method=method, message="slow down", retry_after=17))
    await dispatcher.dispatch(session, bot)
    row = await note(session, notification_id)
    assert row.status == NotificationStatus.PENDING and row.attempts == 0
    assert row.send_after == clock.now() + timedelta(seconds=17)


async def test_a_user_who_blocked_the_bot_is_skipped_and_loses_can_message(
    session: AsyncSession, bot: FakeBot
) -> None:
    _gm, player, _ = await reachable_pair(session)
    notification_id = await pending_note(session, player)
    method = SendMessage(chat_id=1, text="x")
    bot.fail_next(TelegramForbiddenError(method=method, message="bot was blocked by the user"))
    await dispatcher.dispatch(session, bot)
    assert (await note(session, notification_id)).status == NotificationStatus.SKIPPED
    can_message = await session.scalar(
        select(User.can_message)
        .where(User.id == ident(player))
        .execution_options(populate_existing=True)
    )
    assert can_message is False


async def test_deleted_recipients_get_nothing_and_their_rows_are_removed(
    session: AsyncSession, bot: FakeBot
) -> None:
    _gm, player, _ = await reachable_pair(session)
    notification_id = await pending_note(session, player)
    # Deferred rows go too: their payload must not outlive the account.
    later = enqueue(
        session,
        recipient_id=player.id,
        type="quest_offered",
        category=NotificationCategory.QUESTS,
        entity_type=None,
        entity_id=None,
        payload={"title": "Later"},
        send_after=clock.now() + timedelta(days=1),
    )
    await session.execute(
        update(User)
        .where(User.id == player.id)
        .values(deleted_at=clock.now(), tg_user_id=-player.id)
    )
    await session.commit()
    result = await dispatcher.dispatch(session, bot)
    assert result.deleted == 2 and result.sent == []
    remaining = await session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.id.in_([notification_id, later.id]))
    )
    assert remaining == 0
    assert bot.messages == []


async def test_reward_and_partnership_notifications_carry_their_deep_links(
    client: httpx.AsyncClient, session: AsyncSession, bot: FakeBot
) -> None:
    gm, player, partnership_id = await reachable_pair(session)
    reward = await client.post(
        "/api/rewards", headers=auth(gm), json={"title": "Movie night", "price": 10}
    )
    assert reward.status_code == 201, reward.text
    reward_id = reward.json()["id"]
    [created] = bot.messages
    assert button_url(created) == f"https://t.me/telerpg_bot/play?startapp=rw_{reward_id}"
    rows = list(
        await session.scalars(select(Notification).where(Notification.type == "reward_created"))
    )
    assert [r.deep_link for r in rows] == [f"rw_{reward_id}"]
    left = await client.post(
        "/api/partnership/leave", headers=auth(player), json={"confirm_text": "LEAVE"}
    )
    assert left.status_code < 300, left.text
    ended = await session.scalar(
        select(Notification).where(Notification.type == "partnership_ended")
    )
    assert ended is not None and ended.deep_link == f"p_{partnership_id}"


async def test_two_dispatchers_never_send_a_row_twice(
    independent_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with independent_sessions() as s:
        _gm, player, _ = await reachable_pair(s)
        for i in range(20):
            enqueue(
                s,
                recipient_id=player.id,
                type="quest_offered",
                category=NotificationCategory.QUESTS,
                entity_type=None,
                entity_id=None,
                payload={"title": f"Q{i}"},
            )
        await s.commit()
    fake = FakeBot()

    async def run() -> dispatcher.DispatchResult:
        async with independent_sessions() as s:
            return await dispatcher.dispatch(s, fake)

    results = await asyncio.gather(run(), run(), run())
    sent = [i for r in results for i in r.sent]
    assert len(sent) == 20 and len(set(sent)) == 20
    assert len(fake.messages) == 20


# --- expiry, reminders and the daily summary ---------------------------------------------------


async def test_expiry_notifies_both_members(session: AsyncSession, bot: FakeBot) -> None:
    gm, player, _ = await reachable_pair(session)
    occurrence_id = await active_quest(
        session, gm, player, deadline_at=clock.now() + timedelta(hours=1)
    )
    await drain(session, bot)
    clock.freeze(clock.now() + timedelta(hours=2))
    assert await expire_occurrences.run(session) == 1
    rows = list(
        await session.scalars(
            select(Notification)
            .where(Notification.type == "quest_expired")
            .order_by(Notification.recipient_id)
        )
    )
    assert sorted(r.recipient_id for r in rows) == sorted([ident(gm), ident(player)])
    assert all(r.deep_link == f"q_{occurrence_id}" for r in rows)
    await dispatcher.dispatch(session, bot)
    assert [m.text for m in bot.messages] == ["Quest expired: Morning run"] * 2


async def reminders_of(session: AsyncSession) -> list[Notification]:
    return list(
        await session.scalars(
            select(Notification)
            .where(Notification.type == notification_jobs.REMINDER_TYPE)
            .execution_options(populate_existing=True)
        )
    )


async def test_deadline_reminder_once_per_occurrence(
    session: AsyncSession, bot: FakeBot, frozen_clock: ModuleType
) -> None:
    gm, player, _ = await reachable_pair(session)
    due_soon = await active_quest(session, gm, player, deadline_at=clock.now() + timedelta(hours=2))
    await active_quest(
        session, gm, player, title="Later", deadline_at=clock.now() + timedelta(hours=5)
    )
    await drain(session, bot)
    assert await notification_jobs.deadline_reminders(session) == 1
    assert await notification_jobs.deadline_reminders(session) == 0
    frozen_clock.advance(timedelta(minutes=30))
    assert await notification_jobs.deadline_reminders(session) == 0
    [reminder] = await reminders_of(session)
    assert reminder.recipient_id == player.id and reminder.entity_id == due_soon
    assert reminder.category == NotificationCategory.REMINDERS
    assert reminder.deep_link == f"q_{due_soon}"
    await dispatcher.dispatch(session, bot)
    [message] = bot.messages
    assert message.text == "Reminder: Morning run is due soon"
    assert button_url(message) == f"https://t.me/telerpg_bot/play?startapp=q_{due_soon}"
    # Two hours later the second quest enters the window: its own single reminder.
    frozen_clock.advance(timedelta(hours=2))
    assert await notification_jobs.deadline_reminders(session) == 1


async def test_no_reminder_for_finished_quests_or_deleted_players(session: AsyncSession) -> None:
    gm, player, _ = await reachable_pair(session)
    in_review = await active_quest(
        session, gm, player, deadline_at=clock.now() + timedelta(hours=1)
    )
    await session.execute(
        update(QuestOccurrence)
        .where(QuestOccurrence.id == in_review)
        .values(status=QuestOccurrenceStatus.IN_REVIEW)
    )
    gm2, gone, _ = await reachable_pair(session)
    await active_quest(session, gm2, gone, deadline_at=clock.now() + timedelta(hours=1))
    await session.execute(
        update(User).where(User.id == gone.id).values(deleted_at=clock.now(), tg_user_id=-gone.id)
    )
    await session.commit()
    assert await notification_jobs.deadline_reminders(session) == 0


async def test_reminders_wait_out_quiet_hours(
    session: AsyncSession, frozen_clock: ModuleType
) -> None:
    gm, player, _ = await reachable_pair(
        session, notification_prefs={"quiet_hours_start": "11:00", "quiet_hours_end": "12:30"}
    )
    await active_quest(session, gm, player, deadline_at=clock.now() + timedelta(hours=2))
    assert await notification_jobs.deadline_reminders(session) == 0
    frozen_clock.advance(timedelta(minutes=30))
    assert await notification_jobs.deadline_reminders(session) == 1


async def summaries_of(session: AsyncSession) -> list[Notification]:
    return list(
        await session.scalars(
            select(Notification).where(Notification.type == notification_jobs.SUMMARY_TYPE)
        )
    )


async def test_daily_summary_at_nine_local_once_per_day(
    session: AsyncSession, bot: FakeBot, frozen_clock: ModuleType
) -> None:
    gm, player, _ = await reachable_pair(session, timezone="America/Sao_Paulo")  # UTC-3
    await active_quest(session, gm, player)
    await drain(session, bot)
    frozen_clock.freeze(clock.now().replace(hour=11, minute=59))  # 08:59 local
    assert await notification_jobs.daily_summary(session) == 0
    frozen_clock.advance(timedelta(minutes=1))  # 09:00 local
    assert await notification_jobs.daily_summary(session) == 1
    frozen_clock.advance(timedelta(minutes=5))
    assert await notification_jobs.daily_summary(session) == 0
    [summary] = await summaries_of(session)
    assert summary.recipient_id == player.id
    assert summary.payload == {"active": 1, "offers": 0, "reviews": 0}
    assert summary.category == NotificationCategory.SUMMARY
    await dispatcher.dispatch(session, bot)
    [message] = bot.messages
    assert message.text.startswith("Good morning! Active quests: 1.")
    assert button_url(message) == "https://t.me/telerpg_bot/play"
    # The next local morning brings a new one.
    frozen_clock.advance(timedelta(days=1))
    assert await notification_jobs.daily_summary(session) == 1


async def test_daily_summary_skips_quiet_hours_opt_out_and_empty_days(
    session: AsyncSession, frozen_clock: ModuleType
) -> None:
    gm, player, _ = await reachable_pair(
        session,
        notification_prefs={"quiet_hours_start": "08:00", "quiet_hours_end": "10:00"},
    )
    await active_quest(session, gm, player)
    frozen_clock.freeze(clock.now().replace(hour=9, minute=30))
    # The player is inside quiet hours; the GM has nothing to report.
    assert await notification_jobs.daily_summary(session) == 0
    frozen_clock.advance(timedelta(minutes=30))  # 10:00, quiet hours are over
    assert await notification_jobs.daily_summary(session) == 1
    player.notification_prefs = {"daily_summary": False}
    await session.commit()
    frozen_clock.advance(timedelta(days=1))
    assert await notification_jobs.daily_summary(session) == 0


async def test_the_dedupe_index_backs_up_concurrent_job_runs(session: AsyncSession) -> None:
    _gm, player, _ = await reachable_pair(session)
    values: dict[str, Any] = {
        "recipient_id": player.id,
        "type": notification_jobs.SUMMARY_TYPE,
        "category": NotificationCategory.SUMMARY,
        "entity_type": None,
        "entity_id": None,
        "payload": {"active": 1},
        "deep_link": None,
        "send_after": clock.now(),
    }
    assert await notification_jobs._insert_deduped(session, **values) is True
    values["send_after"] = clock.now() + timedelta(hours=1)  # same UTC day
    assert await notification_jobs._insert_deduped(session, **values) is False


def test_runner_schedules_the_notification_jobs() -> None:
    assert DEFAULT_JOBS["dispatch_outbox"].seconds == 30
    assert DEFAULT_JOBS["deadline_reminders"].fn is notification_jobs.deadline_reminders
    assert DEFAULT_JOBS["daily_summary"].fn is notification_jobs.daily_summary


async def test_sweep_job_uses_the_process_bot(session: AsyncSession, bot: FakeBot) -> None:
    _gm, player, _ = await reachable_pair(session)
    notification_id = await pending_note(session, player)
    result = await notification_jobs.dispatch_outbox(session)
    assert result.sent == [notification_id] and len(bot.messages) == 1


# --- inbox API -------------------------------------------------------------------------------


async def make_notes(session: AsyncSession, user: User, n: int) -> list[int]:
    ids = []
    for i in range(n):
        row = enqueue(
            session,
            recipient_id=user.id,
            type="quest_offered",
            category=NotificationCategory.QUESTS,
            entity_type="quest_occurrence",
            entity_id=i + 1,
            payload={"title": f"Q{i}"},
        )
        await session.flush()
        ids.append(row.id)
    await session.commit()
    return ids


async def test_inbox_cursor_pages_newest_first(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    gm, player, _ = await reachable_pair(session)
    ids = await make_notes(session, player, 5)
    await make_notes(session, gm, 2)
    first = await client.get("/api/notifications?limit=2", headers=auth(player))
    assert first.status_code == 200
    body = first.json()
    assert [i["id"] for i in body["items"]] == ids[::-1][:2]
    assert body["unread_count"] == 5
    assert body["items"][0]["deep_link"] == "q_5"
    seen = [i["id"] for i in body["items"]]
    cursor = body["next_cursor"]
    while cursor is not None:
        page = await client.get(f"/api/notifications?limit=2&cursor={cursor}", headers=auth(player))
        seen += [i["id"] for i in page.json()["items"]]
        cursor = page.json()["next_cursor"]
    assert seen == ids[::-1]
    count = await client.get("/api/notifications/unread-count", headers=auth(player))
    assert count.json() == {"count": 5}


async def test_read_one_and_read_all(client: httpx.AsyncClient, session: AsyncSession) -> None:
    gm, player, _ = await reachable_pair(session)
    ids = await make_notes(session, player, 3)
    [gm_note] = await make_notes(session, gm, 1)
    read = await client.post(f"/api/notifications/{ids[0]}/read", headers=auth(player))
    assert read.status_code == 200 and read.json()["read_at"] is not None
    # Someone else's notification does not exist for me.
    other = await client.post(f"/api/notifications/{gm_note}/read", headers=auth(player))
    assert other.status_code == 404
    missing = await client.post("/api/notifications/999999/read", headers=auth(player))
    assert missing.status_code == 404
    count = await client.get("/api/notifications/unread-count", headers=auth(player))
    assert count.json() == {"count": 2}
    everything = await client.post("/api/notifications/read-all", headers=auth(player))
    assert everything.json() == {"updated": 2}
    count = await client.get("/api/notifications/unread-count", headers=auth(player))
    assert count.json() == {"count": 0}
    gm_count = await client.get("/api/notifications/unread-count", headers=auth(gm))
    assert gm_count.json() == {"count": 1}


async def test_inbox_requires_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/notifications")).status_code == 401
    assert (await client.patch("/api/notifications/preferences", json={})).status_code == 401


async def test_preferences_patch_merges_and_validates(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    _gm, player, _ = await reachable_pair(session)
    got = await client.get("/api/notifications/preferences", headers=auth(player))
    assert got.json() == {
        "categories": {c.value: True for c in NotificationCategory},
        "quiet_hours_start": "23:00",
        "quiet_hours_end": "08:00",
        "daily_summary": True,
        "can_message": True,
    }
    patched = await client.patch(
        "/api/notifications/preferences",
        headers=auth(player),
        json={"categories": {"rewards": False}, "quiet_hours_start": "22:30"},
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["categories"]["rewards"] is False and body["categories"]["quests"] is True
    assert (body["quiet_hours_start"], body["quiet_hours_end"]) == ("22:30", "08:00")
    off = await client.patch(
        "/api/notifications/preferences",
        headers=auth(player),
        json={"quiet_hours_start": None, "quiet_hours_end": None, "daily_summary": False},
    )
    assert off.json()["quiet_hours_start"] is None and off.json()["daily_summary"] is False
    assert off.json()["categories"]["rewards"] is False
    for bad in (
        {"quiet_hours_start": "25:00"},
        {"categories": {"spam": True}},
        {"quiet_hours_end": "07:00"},  # start is still null
        {"unknown": 1},
    ):
        response = await client.patch(
            "/api/notifications/preferences", headers=auth(player), json=bad
        )
        assert response.status_code == 422, bad
    stored = await session.scalar(
        select(User.notification_prefs)
        .where(User.id == ident(player))
        .execution_options(populate_existing=True)
    )
    assert stored is not None and stored["daily_summary"] is False


async def test_write_access_records_can_message(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    _gm, player, _ = await reachable_pair(session, can_message=False)
    granted = await client.post(
        "/api/notifications/write-access", headers=auth(player), json={"allowed": True}
    )
    assert granted.status_code == 200 and granted.json()["can_message"] is True
    denied = await client.post(
        "/api/notifications/write-access", headers=auth(player), json={"allowed": False}
    )
    assert denied.json()["can_message"] is False
    bad = await client.post("/api/notifications/write-access", headers=auth(player), json={})
    assert bad.status_code == 422


async def test_voucher_links_point_each_side_to_its_screen(
    session: AsyncSession,
) -> None:
    gm, player, partnership = await pair(session)
    reward = await factories.create_reward(session, partnership, gm)
    purchase = RewardPurchase(
        reward_id=reward.id,
        partnership_id=partnership.id,
        buyer_id=player.id,
        provider_id=gm.id,
        price_paid=10,
        reward_snapshot={
            "reward_id": reward.id,
            "title": "Movie night",
            "description": None,
            "price": 10,
            "image_file_id": None,
            "cooldown_days": None,
            "quantity_limit": None,
        },
        idempotency_key="k1",
    )
    session.add(purchase)
    await session.flush()
    voucher_event(
        session,
        actor_id=player.id,
        recipient_id=gm.id,
        type_="reward_requested",
        purchase=purchase,
    )
    voucher_event(
        session,
        actor_id=gm.id,
        recipient_id=player.id,
        type_="reward_scheduled",
        purchase=purchase,
    )
    await session.flush()
    links = dict(
        (
            await session.execute(
                select(Notification.type, Notification.deep_link).where(
                    Notification.entity_type == "reward_purchase"
                )
            )
        ).all()
    )
    assert links == {
        "reward_requested": f"rq_{purchase.id}",
        "reward_scheduled": f"r_{purchase.id}",
    }
