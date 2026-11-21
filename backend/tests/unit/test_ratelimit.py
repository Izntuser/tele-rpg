from datetime import timedelta
from types import ModuleType

import pytest

from app.core import ratelimit
from app.core.ratelimit import WRITE_LIMIT, Limit, RateLimiter


def test_write_limit_is_30_per_minute() -> None:
    assert WRITE_LIMIT == Limit(capacity=30, per_seconds=60)
    assert ratelimit.UPLOAD_LIMIT == Limit(capacity=5, per_seconds=60)


def test_bucket_allows_capacity_then_denies(frozen_clock: ModuleType) -> None:
    limiter = RateLimiter(WRITE_LIMIT)
    assert all(limiter.hit("u1").allowed for _ in range(30))
    denied = limiter.hit("u1")
    assert not denied.allowed
    assert denied.retry_after == 2  # one token per 2 s at 30/min


def test_bucket_refills_over_time(frozen_clock: ModuleType) -> None:
    limiter = RateLimiter(WRITE_LIMIT)
    for _ in range(30):
        limiter.hit("u1")
    frozen_clock.advance(timedelta(seconds=1))
    assert not limiter.hit("u1").allowed
    frozen_clock.advance(timedelta(seconds=1))
    assert limiter.hit("u1").allowed
    assert not limiter.hit("u1").allowed
    frozen_clock.advance(timedelta(minutes=1))
    assert sum(limiter.hit("u1").allowed for _ in range(40)) == 30


def test_keys_are_independent(frozen_clock: ModuleType) -> None:
    limiter = RateLimiter(Limit(capacity=2, per_seconds=60))
    assert limiter.hit("a").allowed and limiter.hit("a").allowed
    assert not limiter.hit("a").allowed
    assert limiter.hit("b").allowed


def test_clock_going_backwards_does_not_mint_tokens(frozen_clock: ModuleType) -> None:
    limiter = RateLimiter(Limit(capacity=1, per_seconds=60))
    assert limiter.hit("a").allowed
    frozen_clock.advance(timedelta(minutes=-10))
    assert not limiter.hit("a").allowed


def test_idle_buckets_are_pruned_when_full(frozen_clock: ModuleType) -> None:
    limiter = RateLimiter(Limit(capacity=1, per_seconds=60), max_keys=3)
    for key in ("a", "b", "c"):
        limiter.hit(key)
    assert len(limiter) == 3
    frozen_clock.advance(timedelta(minutes=2))  # all three refilled -> idle
    limiter.hit("d")
    assert len(limiter) == 1


def test_active_buckets_survive_pruning(frozen_clock: ModuleType) -> None:
    limiter = RateLimiter(Limit(capacity=1, per_seconds=60), max_keys=2)
    limiter.hit("a")
    limiter.hit("b")
    limiter.hit("c")  # nothing idle to prune: still tracked, and "a" keeps its empty bucket
    assert not limiter.hit("a").allowed


def test_reset_all_clears_buckets(frozen_clock: ModuleType) -> None:
    ratelimit.write_limiter.hit("x")
    ratelimit.reset_all()
    assert len(ratelimit.write_limiter) == 0


@pytest.fixture(autouse=True)
def _clean_global_limiters() -> None:
    ratelimit.reset_all()
