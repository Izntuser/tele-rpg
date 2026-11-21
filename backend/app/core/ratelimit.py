"""In-memory per-key token buckets (one API process; ARCHITECTURE §3 / §7).

``WRITE_LIMIT`` (30/min per user) is applied to every authenticated write request by
``app.core.deps.current_user``; ``UPLOAD_LIMIT`` (5/min) is for upload routes. Time comes from
``app.core.clock`` so tests can freeze and advance it. Swap for Redis behind the same
``RateLimiter.hit`` interface if the API ever runs more than one replica.
"""

import math
import threading
from dataclasses import dataclass
from datetime import datetime

from app.core import clock


@dataclass(frozen=True, slots=True)
class Limit:
    capacity: int
    per_seconds: float

    @property
    def rate(self) -> float:
        return self.capacity / self.per_seconds


WRITE_LIMIT = Limit(capacity=30, per_seconds=60)
UPLOAD_LIMIT = Limit(capacity=5, per_seconds=60)
# Unauthenticated login attempts per client address (HMAC failures are cheap, upserts are not).
LOGIN_LIMIT = Limit(capacity=30, per_seconds=60)

# Above this many tracked keys, fully refilled (idle) buckets are dropped to bound memory.
MAX_KEYS = 10_000


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated: datetime


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    retry_after: int  # whole seconds until one token is available (0 when allowed)


class RateLimiter:
    def __init__(self, limit: Limit, max_keys: int = MAX_KEYS) -> None:
        self.limit = limit
        self.max_keys = max_keys
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def _refill(self, bucket: _Bucket, now: datetime) -> None:
        elapsed = max(0.0, (now - bucket.updated).total_seconds())
        bucket.tokens = min(self.limit.capacity, bucket.tokens + elapsed * self.limit.rate)
        bucket.updated = now

    def _prune(self, now: datetime) -> None:
        for key in list(self._buckets):
            bucket = self._buckets[key]
            self._refill(bucket, now)
            if bucket.tokens >= self.limit.capacity:
                del self._buckets[key]

    def hit(self, key: str) -> Decision:
        """Take one token for ``key``; ``allowed`` is False when the bucket is empty."""
        now = clock.now()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) >= self.max_keys:
                    self._prune(now)
                bucket = _Bucket(tokens=float(self.limit.capacity), updated=now)
                self._buckets[key] = bucket
            else:
                self._refill(bucket, now)
            if bucket.tokens >= 1:
                bucket.tokens -= 1
                return Decision(allowed=True, retry_after=0)
            wait = (1 - bucket.tokens) / self.limit.rate
            return Decision(allowed=False, retry_after=max(1, math.ceil(wait)))

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()

    def __len__(self) -> int:
        return len(self._buckets)


write_limiter = RateLimiter(WRITE_LIMIT)
upload_limiter = RateLimiter(UPLOAD_LIMIT)
login_limiter = RateLimiter(LOGIN_LIMIT)


def reset_all() -> None:
    for limiter in (write_limiter, upload_limiter, login_limiter):
        limiter.reset()
