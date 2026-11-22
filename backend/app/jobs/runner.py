"""The scheduler process: ``python -m app.jobs.runner`` (DECISIONS 1).

Jobs start only after this process holds the Postgres session advisory lock
``pg_try_advisory_lock(LEADER_LOCK_KEY)`` on a dedicated connection. A second runner finds the
lock taken, runs nothing and keeps retrying, so it takes over when the first one dies (Postgres
drops the lock with the connection). Jobs are idempotent anyway; the lock only avoids the work
and the noise of two runners.
"""

import asyncio
import contextlib
import logging
import signal
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker

from app.bot.dispatcher import close_bot
from app.core import idempotency
from app.core.config import get_settings
from app.core.db import make_engine
from app.core.logging import configure_logging
from app.db.session import make_sessionmaker
from app.jobs import expire_occurrences, generate_occurrences, notification_jobs

log = logging.getLogger("app.jobs.runner")

#: Arbitrary application-wide constant ("tele" in hex).
LEADER_LOCK_KEY = 0x74656C65
RETRY_SECONDS = 30.0

JobFn = Callable[[AsyncSession], Awaitable[object]]


@dataclass(frozen=True, slots=True)
class JobSpec:
    fn: JobFn
    seconds: float


async def _purge_idempotency(session: AsyncSession) -> int:
    deleted = await idempotency.purge_expired(session)
    await session.commit()
    return deleted


#: Time zones differ by 15-minute steps, so the day / week boundary jobs (and the 09:00-local
#: summary) run that often. The outbox sweep is the API post-commit send's fallback (30 s).
DEFAULT_JOBS: Mapping[str, JobSpec] = {
    "generate_occurrences": JobSpec(generate_occurrences.run, 5 * 60),
    "expire_occurrences": JobSpec(expire_occurrences.run, 5 * 60),
    "purge_idempotency": JobSpec(_purge_idempotency, 60 * 60),
    "dispatch_outbox": JobSpec(notification_jobs.dispatch_outbox, 30),
    "deadline_reminders": JobSpec(notification_jobs.deadline_reminders, 5 * 60),
    "daily_summary": JobSpec(notification_jobs.daily_summary, 5 * 60),
}


async def try_lead(engine: AsyncEngine) -> AsyncConnection | None:
    """The connection holding the leader lock, or None when another runner has it. The lock
    lives as long as the returned connection stays open."""
    conn = await engine.connect()
    try:
        got = await conn.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": LEADER_LOCK_KEY})
        await conn.commit()
    except BaseException:
        await conn.close()
        raise
    if got:
        return conn
    await conn.close()
    return None


class Runner:
    def __init__(
        self,
        engine: AsyncEngine,
        sessions: async_sessionmaker[AsyncSession],
        jobs: Mapping[str, JobSpec] = DEFAULT_JOBS,
        *,
        retry_seconds: float = RETRY_SECONDS,
        max_concurrent_jobs: int | None = None,
    ) -> None:
        self._engine = engine
        self._sessions = sessions
        self._jobs = jobs
        self._retry = retry_seconds
        #: Bounds concurrent DB sessions (NullPool: one connection each) so the 6 jobs that all
        #: fire at startup do not exhaust a small pooler. The leader-lock connection is separate.
        limit = (
            get_settings().scheduler_max_concurrent_jobs
            if max_concurrent_jobs is None
            else max_concurrent_jobs
        )
        if limit < 1:
            raise ValueError("max_concurrent_jobs must be at least 1")
        self._slots = asyncio.Semaphore(limit)
        self._stop = asyncio.Event()
        #: True while this runner holds the lock and its scheduler is running.
        self.leading = False

    def stop(self) -> None:
        self._stop.set()

    async def _run_job(self, name: str, spec: JobSpec) -> None:
        try:
            async with self._slots, self._sessions() as session:
                await spec.fn(session)
        except Exception:
            log.exception("job %s failed", name)

    async def _wait(self, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stop.wait(), seconds)

    async def run(self) -> None:
        """Block until ``stop()``: wait for the leader lock, run the jobs while holding it."""
        while not self._stop.is_set():
            try:
                conn = await try_lead(self._engine)
            except Exception as exc:
                # e.g. the pooler refused the connection; never log the URL or its password.
                log.error("leader lock attempt failed (%s); retrying", type(exc).__name__)
                await self._wait(self._retry)
                continue
            if conn is None:
                log.info("another runner holds the leader lock; waiting")
                await self._wait(self._retry)
                continue
            scheduler = AsyncIOScheduler(timezone="UTC")
            for name, spec in self._jobs.items():
                scheduler.add_job(
                    self._run_job,
                    "interval",
                    args=[name, spec],
                    seconds=spec.seconds,
                    id=name,
                    max_instances=1,
                    coalesce=True,
                    next_run_time=datetime.now(UTC),
                )
            scheduler.start()
            self.leading = True
            log.info("leader lock acquired; running %s", ", ".join(self._jobs))
            try:
                await self._stop.wait()
            finally:
                self.leading = False
                scheduler.shutdown(wait=False)
                with contextlib.suppress(Exception):
                    await conn.execute(
                        text("SELECT pg_advisory_unlock(:k)"), {"k": LEADER_LOCK_KEY}
                    )
                await conn.close()


async def main() -> None:
    configure_logging()
    engine = make_engine()
    runner = Runner(engine, make_sessionmaker(engine))
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, runner.stop)
    try:
        await runner.run()
    finally:
        await close_bot()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
