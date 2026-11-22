"""The scheduler: the advisory-locked runner, occurrence generation, expiry and daily streaks."""

import asyncio
from collections.abc import Callable
from datetime import date, timedelta
from types import ModuleType
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core import clock, ratelimit
from app.core.config import get_settings
from app.db.session import make_sessionmaker
from app.jobs import expire_occurrences, generate_occurrences
from app.jobs.runner import JobSpec, Runner, try_lead
from app.modules.common.enums import QuestOccurrenceStatus, QuestTemplateStatus
from app.modules.quests import service
from app.modules.quests.models import QuestOccurrence, QuestStreak, QuestTemplate
from app.modules.quests.schemas import QuestCreate
from app.modules.users.models import User
from tests.integration.completion_support import active_quest, auth, pair


@pytest.fixture(autouse=True)
def _clean_limiters() -> None:
    ratelimit.reset_all()


async def template_of(session: AsyncSession, occurrence_id: int) -> int:
    template_id = await session.scalar(
        select(QuestOccurrence.template_id).where(QuestOccurrence.id == occurrence_id)
    )
    assert template_id is not None
    return template_id


async def occurrences(session: AsyncSession, template_id: int) -> list[QuestOccurrence]:
    rows = await session.scalars(
        select(QuestOccurrence)
        .where(QuestOccurrence.template_id == template_id)
        .order_by(QuestOccurrence.scheduled_date)
        .execution_options(populate_existing=True)
    )
    return list(rows)


async def streak_of(session: AsyncSession, template_id: int) -> tuple[int, int]:
    row = await session.scalar(
        select(QuestStreak)
        .where(QuestStreak.template_id == template_id)
        .execution_options(populate_existing=True)
    )
    return (row.current, row.best) if row is not None else (0, 0)


async def set_timezone(session: AsyncSession, user: User, tz: str) -> None:
    user.timezone = tz
    await session.commit()


# --- the runner and its advisory lock ---------------------------------------------------------


async def eventually(check: Callable[[], bool], limit: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + limit
    while not check():
        assert asyncio.get_running_loop().time() < deadline, "condition not reached"
        await asyncio.sleep(0.02)


def counting_job(counter: list[str], name: str) -> JobSpec:
    async def job(_session: AsyncSession) -> None:
        counter.append(name)

    return JobSpec(job, 0.05)


async def test_only_the_runner_holding_the_advisory_lock_runs_jobs(
    db_engine: AsyncEngine,
) -> None:
    sessions = make_sessionmaker(db_engine)
    ran_a: list[str] = []
    ran_b: list[str] = []
    a = Runner(db_engine, sessions, {"tick": counting_job(ran_a, "a")}, retry_seconds=0.05)
    b = Runner(db_engine, sessions, {"tick": counting_job(ran_b, "b")}, retry_seconds=0.05)
    task_a = asyncio.create_task(a.run())
    await eventually(lambda: a.leading)
    task_b = asyncio.create_task(b.run())
    try:
        await eventually(lambda: len(ran_a) >= 3)
        await asyncio.sleep(0.4)  # many retry rounds for B
        assert not b.leading
        assert ran_b == []
        assert len(ran_a) >= 3

        # The leader going away hands the lock (and the work) to the standby.
        a.stop()
        await asyncio.wait_for(task_a, 5)
        await eventually(lambda: b.leading)
        await eventually(lambda: len(ran_b) >= 2)
    finally:
        a.stop()
        b.stop()
        await asyncio.wait_for(asyncio.gather(task_a, task_b), 5)
    assert not a.leading and not b.leading


async def test_try_lead_is_exclusive_until_the_connection_closes(db_engine: AsyncEngine) -> None:
    first = await try_lead(db_engine)
    assert first is not None
    assert await try_lead(db_engine) is None
    await first.close()  # Postgres drops a session lock with its connection
    again = await try_lead(db_engine)
    assert again is not None
    await again.close()


async def test_a_failing_job_does_not_stop_the_runner(db_engine: AsyncEngine) -> None:
    ran: list[str] = []

    async def boom(_session: AsyncSession) -> None:
        raise RuntimeError("boom")

    runner = Runner(
        db_engine,
        make_sessionmaker(db_engine),
        {"boom": JobSpec(boom, 0.05), "ok": counting_job(ran, "ok")},
    )
    task = asyncio.create_task(runner.run())
    try:
        await eventually(lambda: len(ran) >= 3)
    finally:
        runner.stop()
        await asyncio.wait_for(task, 5)


async def test_concurrent_jobs_are_capped_and_the_leader_lock_is_unaffected(
    db_engine: AsyncEngine,
) -> None:
    running = 0
    peak = 0
    done: list[str] = []

    def slow(name: str) -> JobSpec:
        async def job(_session: AsyncSession) -> None:
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.1)
            running -= 1
            done.append(name)

        return JobSpec(job, 3600)

    jobs = {f"j{i}": slow(f"j{i}") for i in range(6)}
    runner = Runner(db_engine, make_sessionmaker(db_engine), jobs, max_concurrent_jobs=2)
    task = asyncio.create_task(runner.run())
    try:
        await eventually(lambda: len(done) == 6)
        assert peak == 2  # all 6 fired at once; 2 ran at a time, the rest waited their turn
        assert runner.leading
        assert await try_lead(db_engine) is None  # the lock is still held
    finally:
        runner.stop()
        await asyncio.wait_for(task, 5)


# --- generate_occurrences ---------------------------------------------------------------------


async def test_generates_each_days_occurrence_once_and_never_backfills(
    session: AsyncSession, frozen_clock: ModuleType
) -> None:
    gm, player, _ = await pair(session)
    occ = await active_quest(session, gm, player, recurrence="daily")  # Thu 2026-01-15
    template_id = await template_of(session, occ)

    assert await generate_occurrences.run(session) == 0  # today's exists already
    assert await generate_occurrences.run(session) == 0

    frozen_clock.advance(timedelta(days=1))  # Fri
    assert await generate_occurrences.run(session) == 1
    assert await generate_occurrences.run(session) == 0  # repeated run / restart
    rows = await occurrences(session, template_id)
    assert [r.scheduled_date for r in rows] == [date(2026, 1, 15), date(2026, 1, 16)]
    assert rows[-1].status == QuestOccurrenceStatus.ACTIVE
    assert rows[-1].terms_snapshot["gold"] == 40

    frozen_clock.advance(timedelta(days=3))  # Mon 01-19: the 17th and 18th are never created
    assert await generate_occurrences.run(session) == 1
    rows = await occurrences(session, template_id)
    assert [r.scheduled_date for r in rows] == [
        date(2026, 1, 15),
        date(2026, 1, 16),
        date(2026, 1, 19),
    ]


async def test_weekly_quests_get_the_iso_weeks_monday(
    session: AsyncSession, frozen_clock: ModuleType
) -> None:
    gm, player, _ = await pair(session)
    occ = await active_quest(session, gm, player, recurrence="weekly")  # Thu 2026-01-15
    template_id = await template_of(session, occ)
    assert (await occurrences(session, template_id))[0].scheduled_date == date(2026, 1, 12)

    frozen_clock.advance(timedelta(days=3))  # Sun 01-18, still that week
    assert await generate_occurrences.run(session) == 0
    frozen_clock.advance(timedelta(days=1))  # Mon 01-19
    assert await generate_occurrences.run(session) == 1
    assert await generate_occurrences.run(session) == 0
    rows = await occurrences(session, template_id)
    assert [r.scheduled_date for r in rows] == [date(2026, 1, 12), date(2026, 1, 19)]
    assert rows[-1].due_at is not None
    assert rows[-1].due_at.date() == date(2026, 1, 26)


async def test_generation_follows_the_assignees_timezone(
    session: AsyncSession, frozen_clock: ModuleType
) -> None:
    gm, player, _ = await pair(session)
    await set_timezone(session, player, "Europe/Kyiv")
    occ = await active_quest(session, gm, player, recurrence="daily")
    template_id = await template_of(session, occ)  # Jan 15 12:00Z = 14:00 Kyiv
    assert await generate_occurrences.run(session) == 0

    frozen_clock.advance(timedelta(hours=9, minutes=59))  # 21:59Z, 23:59 in Kyiv
    assert await generate_occurrences.run(session) == 0
    frozen_clock.advance(timedelta(minutes=1))  # 22:00Z is Kyiv midnight; UTC is still Jan 15
    assert await generate_occurrences.run(session) == 1
    rows = await occurrences(session, template_id)
    assert rows[-1].scheduled_date == date(2026, 1, 16)
    assert rows[-1].due_at is not None
    assert rows[-1].due_at.isoformat().startswith("2026-01-16T22:00")


async def test_paused_cancelled_and_unaccepted_quests_are_skipped(
    session: AsyncSession, frozen_clock: ModuleType
) -> None:
    gm, player, _ = await pair(session)
    paused = await template_of(session, await active_quest(session, gm, player, recurrence="daily"))
    cancelled = await template_of(
        session, await active_quest(session, gm, player, recurrence="daily")
    )
    offered = (
        await service.create(
            session,
            gm,
            get_settings(),
            QuestCreate(title="Unaccepted", attribute="intellectual", gold=10, recurrence="daily"),
        )
    ).template.id
    await service.set_paused(session, gm, paused, paused=True)
    await service.cancel(session, gm, template_id=cancelled)

    frozen_clock.advance(timedelta(days=1))
    assert await generate_occurrences.run(session) == 0
    assert len(await occurrences(session, paused)) == 1
    assert len(await occurrences(session, cancelled)) == 1
    assert await occurrences(session, offered) == []

    template = await session.get(QuestTemplate, paused, populate_existing=True)
    assert template is not None and template.status == QuestTemplateStatus.PAUSED


async def test_deleted_assignee_gets_nothing(
    session: AsyncSession, frozen_clock: ModuleType
) -> None:
    gm, player, _ = await pair(session)
    template_id = await template_of(
        session, await active_quest(session, gm, player, recurrence="daily")
    )
    player.deleted_at = clock.now()
    await session.commit()
    frozen_clock.advance(timedelta(days=1))
    assert await generate_occurrences.run(session) == 0
    assert len(await occurrences(session, template_id)) == 1


# --- expire_occurrences -----------------------------------------------------------------------


async def post(
    client: httpx.AsyncClient, user: User, path: str, body: dict[str, Any] | None = None
) -> httpx.Response:
    response = await client.post(f"/api{path}", headers=auth(user), json=body)
    assert response.status_code == 200, response.text
    return response


async def test_expire_moves_overdue_active_occurrences_and_never_touches_in_review(
    client: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    gm, player, _ = await pair(session)
    waiting = await active_quest(session, gm, player, title="In review", recurrence="daily")
    overdue = await active_quest(session, gm, player, title="Overdue", recurrence="daily")
    await post(client, player, f"/quests/{waiting}/submit")

    frozen_clock.advance(timedelta(hours=11, minutes=59))  # 23:59Z, due at midnight
    assert await expire_occurrences.run(session) == 0

    frozen_clock.advance(timedelta(minutes=1))
    assert await expire_occurrences.run(session) == 1
    assert await expire_occurrences.run(session) == 0
    by_id = {
        o.id: o.status
        for o in (
            await session.scalars(select(QuestOccurrence).execution_options(populate_existing=True))
        )
    }
    assert by_id[overdue] == QuestOccurrenceStatus.EXPIRED
    assert by_id[waiting] == QuestOccurrenceStatus.IN_REVIEW

    # The creator can still confirm the in-review one after its day ended.
    await post(client, gm, f"/quests/{waiting}/confirm")


async def test_expire_leaves_future_and_open_ended_occurrences(
    session: AsyncSession, frozen_clock: ModuleType
) -> None:
    gm, player, _ = await pair(session)
    once = await active_quest(session, gm, player, title="No deadline")
    dated = await active_quest(
        session, gm, player, title="Deadline", deadline_at=clock.now() + timedelta(days=2)
    )
    frozen_clock.advance(timedelta(days=1))
    assert await expire_occurrences.run(session) == 0
    frozen_clock.advance(timedelta(days=2))
    assert await expire_occurrences.run(session) == 1
    statuses = {
        o.id: o.status
        for o in await session.scalars(
            select(QuestOccurrence).execution_options(populate_existing=True)
        )
    }
    assert statuses[once] == QuestOccurrenceStatus.ACTIVE
    assert statuses[dated] == QuestOccurrenceStatus.EXPIRED


# --- daily streaks ----------------------------------------------------------------------------


async def complete_today(
    client: httpx.AsyncClient, session: AsyncSession, gm: User, player: User, template_id: int
) -> None:
    today = clock.today_in("UTC")
    occurrence_id = await session.scalar(
        select(QuestOccurrence.id).where(
            QuestOccurrence.template_id == template_id, QuestOccurrence.scheduled_date == today
        )
    )
    assert occurrence_id is not None
    await post(client, player, f"/quests/{occurrence_id}/submit")
    await post(client, gm, f"/quests/{occurrence_id}/confirm")


async def test_streak_counts_consecutive_days_and_a_missed_day_resets_current(
    client: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    gm, player, _ = await pair(session)
    template_id = await template_of(
        session, await active_quest(session, gm, player, recurrence="daily")
    )

    await complete_today(client, session, gm, player, template_id)  # Jan 15
    assert await streak_of(session, template_id) == (1, 1)

    frozen_clock.advance(timedelta(days=1))  # Jan 16
    await generate_occurrences.run(session)
    await expire_occurrences.run(session)  # Jan 15 was completed: nothing expires
    assert await streak_of(session, template_id) == (1, 1)
    await complete_today(client, session, gm, player, template_id)
    assert await streak_of(session, template_id) == (2, 2)

    frozen_clock.advance(timedelta(days=1))  # Jan 17: generated, then missed
    await generate_occurrences.run(session)
    assert await streak_of(session, template_id) == (2, 2)  # the day is not over yet
    frozen_clock.advance(timedelta(days=1))  # Jan 18
    assert await expire_occurrences.run(session) == 1
    assert await streak_of(session, template_id) == (0, 2)  # missed day: current resets, best stays

    await generate_occurrences.run(session)
    await complete_today(client, session, gm, player, template_id)
    assert await streak_of(session, template_id) == (1, 2)


async def test_streak_is_read_through_the_template_api(
    client: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    gm, player, _ = await pair(session)
    template_id = await template_of(
        session, await active_quest(session, gm, player, recurrence="daily")
    )
    await complete_today(client, session, gm, player, template_id)
    response = await client.get(f"/api/quest-templates/{template_id}", headers=auth(gm))
    assert response.json()["streak"] == {
        "current": 1,
        "best": 1,
        "last_completed_date": "2026-01-15",
    }
    weekly = await template_of(
        session, await active_quest(session, gm, player, recurrence="weekly")
    )
    response = await client.get(f"/api/quest-templates/{weekly}", headers=auth(gm))
    assert response.json()["streak"] is None


async def test_a_gap_then_an_expired_day_keeps_the_best_streak(
    client: httpx.AsyncClient, session: AsyncSession, frozen_clock: ModuleType
) -> None:
    gm, player, _ = await pair(session)
    template_id = await template_of(
        session, await active_quest(session, gm, player, recurrence="daily")
    )
    await complete_today(client, session, gm, player, template_id)
    frozen_clock.advance(timedelta(days=2))
    await expire_occurrences.run(session)  # no occurrence for Jan 16/17: nothing to expire
    await generate_occurrences.run(session)
    assert await streak_of(session, template_id) == (1, 1)
    # Expiring today's occurrence two days later breaks the streak.
    frozen_clock.advance(timedelta(days=1))
    await expire_occurrences.run(session)
    assert await streak_of(session, template_id) == (0, 1)


async def test_runner_survives_try_lead_errors_and_then_leads(
    db_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.jobs import runner as runner_mod

    real = runner_mod.try_lead
    calls = 0

    async def flaky(engine: AsyncEngine) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("postgresql://u:secret@host/db refused")
        return await real(engine)

    monkeypatch.setattr(runner_mod, "try_lead", flaky)
    runner = Runner(db_engine, make_sessionmaker(db_engine), {}, retry_seconds=0.05)
    task = asyncio.create_task(runner.run())
    try:
        await eventually(lambda: runner.leading)
        assert calls == 2
    finally:
        runner.stop()
        await asyncio.wait_for(task, 5)


def test_runner_rejects_zero_concurrency_and_honours_explicit_values(
    db_engine: AsyncEngine,
) -> None:
    sessions = make_sessionmaker(db_engine)
    with pytest.raises(ValueError):
        Runner(db_engine, sessions, {}, max_concurrent_jobs=0)
    Runner(db_engine, sessions, {}, max_concurrent_jobs=1)
