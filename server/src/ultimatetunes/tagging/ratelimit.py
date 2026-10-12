# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""In-process `RateLimiter` for the worker, and the pacing helper built on it.

The worker has no database (SPEC section 3), so it cannot use `SqliteRateLimiter`. This is the
in-process implementation of the same `RateLimiter` protocol (`core/ratelimit.py`), with the
same arithmetic: token buckets, a failure count with a temporary lockout, purge by last
activity. It runs on the clock's monotonic time. Several worker replicas would need a shared
implementation (Redis, PLAN T26) behind the same protocol. 100 % test coverage (CLAUDE.md).

`wait_for_token` blocks until a bucket gives a token: MusicBrainz allows one request per second
per client (`musicbrainz:global`, `Limit(1.0, 1.0)`).
"""

import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from ultimatetunes.core.clock import Clock
from ultimatetunes.core.ratelimit import ALLOWED, Decision, Limit, RateLimiter


@dataclass
class _Bucket:
    tokens: float
    updated: float
    touched: float
    failures: int = 0
    locked_until: float | None = None


def _ceil_s(seconds: float) -> int:
    return max(1, math.ceil(seconds))


class MemoryRateLimiter:
    """`RateLimiter` in process memory (one worker process)."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._buckets: dict[str, _Bucket] = {}

    def _lockout(self, bucket: _Bucket | None, now: float) -> Decision:
        if bucket is None or bucket.locked_until is None or bucket.locked_until <= now:
            return ALLOWED
        return Decision(allowed=False, retry_after_s=_ceil_s(bucket.locked_until - now))

    def hit(self, key: str, limit: Limit, cost: float = 1.0) -> Decision:
        now = self._clock.monotonic()
        bucket = self._buckets.get(key)
        locked = self._lockout(bucket, now)
        if not locked.allowed:
            return locked
        if bucket is None:
            bucket = _Bucket(tokens=limit.burst, updated=now, touched=now)
            self._buckets[key] = bucket
        else:
            elapsed = max(0.0, now - bucket.updated)
            bucket.tokens = min(limit.burst, bucket.tokens + elapsed * limit.rate_per_s)
            bucket.updated = now
        bucket.touched = now
        if bucket.tokens >= cost:
            bucket.tokens -= cost
            return ALLOWED
        return Decision(
            allowed=False, retry_after_s=_ceil_s((cost - bucket.tokens) / limit.rate_per_s)
        )

    def locked(self, key: str) -> Decision:
        return self._lockout(self._buckets.get(key), self._clock.monotonic())

    def peek(self, key: str, limit: Limit) -> float:
        bucket = self._buckets.get(key)
        if bucket is None:
            return limit.burst
        elapsed = max(0.0, self._clock.monotonic() - bucket.updated)
        return min(limit.burst, bucket.tokens + elapsed * limit.rate_per_s)

    def record_failure(self, key: str, *, max_failures: int, lockout_s: float) -> Decision:
        if max_failures < 1 or lockout_s <= 0:
            raise ValueError("max_failures and lockout_s must be positive")
        now = self._clock.monotonic()
        # A new bucket starts full: the next `hit` caps the tokens to that limit's burst.
        bucket = self._buckets.setdefault(key, _Bucket(tokens=math.inf, updated=now, touched=now))
        bucket.touched = now
        bucket.failures += 1
        if bucket.failures < max_failures:
            return ALLOWED
        bucket.failures = 0
        bucket.locked_until = now + lockout_s
        return Decision(allowed=False, retry_after_s=_ceil_s(lockout_s))

    def record_success(self, key: str) -> None:
        bucket = self._buckets.get(key)
        if bucket is not None:
            bucket.failures = 0
            bucket.touched = self._clock.monotonic()

    def purge_idle(self, idle_s: float) -> int:
        now = self._clock.monotonic()
        idle = [
            key
            for key, bucket in self._buckets.items()
            if bucket.touched < now - idle_s
            and (bucket.locked_until is None or bucket.locked_until <= now)
        ]
        for key in idle:
            del self._buckets[key]
        return len(idle)


async def wait_for_token(
    limiter: RateLimiter, key: str, limit: Limit, sleep: Callable[[float], Awaitable[None]]
) -> None:
    """Waits (with `sleep`) until `limiter` gives one token of `key`."""
    while True:
        decision = limiter.hit(key, limit)
        if decision.allowed:
            return
        await sleep(decision.retry_after_s)
