# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The worker's in-process `RateLimiter` (100 % coverage, same rules as the SQLite one)."""

import pytest

from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.ratelimit import Decision, Limit, RateLimiter
from ultimatetunes.tagging.ratelimit import MemoryRateLimiter, wait_for_token

pytestmark = pytest.mark.anyio
ONE_PER_S = Limit(1.0, 1.0)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_it_is_a_rate_limiter() -> None:
    limiter: RateLimiter = MemoryRateLimiter(FakeClock())
    assert limiter.hit("k", ONE_PER_S).allowed


def test_buckets_refill_over_time() -> None:
    clock = FakeClock()
    limiter = MemoryRateLimiter(clock)
    limit = Limit(rate_per_s=0.5, burst=2)
    assert limiter.hit("k", limit).allowed
    assert limiter.hit("k", limit).allowed
    assert limiter.hit("k", limit) == Decision(allowed=False, retry_after_s=2)
    clock.advance(1)
    assert limiter.hit("k", limit) == Decision(allowed=False, retry_after_s=1)
    clock.advance(1)
    assert limiter.hit("k", limit).allowed
    clock.advance(100)
    assert limiter.hit("k", limit, cost=2).allowed
    assert limiter.hit("other", limit).allowed


def test_failures_lock_the_key_until_the_lockout_ends() -> None:
    clock = FakeClock()
    limiter = MemoryRateLimiter(clock)
    assert limiter.locked("k").allowed
    assert limiter.record_failure("k", max_failures=2, lockout_s=10).allowed
    assert limiter.record_failure("k", max_failures=2, lockout_s=10) == Decision(False, 10)
    assert limiter.locked("k") == Decision(False, 10)
    assert limiter.hit("k", ONE_PER_S) == Decision(False, 10)
    clock.advance(10)
    assert limiter.locked("k").allowed
    assert limiter.hit("k", ONE_PER_S).allowed


def test_success_clears_the_failure_count() -> None:
    limiter = MemoryRateLimiter(FakeClock())
    limiter.record_success("missing")
    limiter.record_failure("k", max_failures=2, lockout_s=10)
    limiter.record_success("k")
    assert limiter.record_failure("k", max_failures=2, lockout_s=10).allowed


@pytest.mark.parametrize(("failures", "lockout"), [(0, 1.0), (1, 0.0)])
def test_failure_limits_must_be_positive(failures: int, lockout: float) -> None:
    with pytest.raises(ValueError, match="positive"):
        MemoryRateLimiter(FakeClock()).record_failure("k", max_failures=failures, lockout_s=lockout)


def test_purge_forgets_idle_keys_but_not_running_lockouts() -> None:
    clock = FakeClock()
    limiter = MemoryRateLimiter(clock)
    limiter.hit("idle", ONE_PER_S)
    limiter.record_failure("locked", max_failures=1, lockout_s=1000)
    limiter.record_failure("expired", max_failures=1, lockout_s=5)
    clock.advance(60)
    limiter.hit("fresh", ONE_PER_S)
    assert limiter.purge_idle(30) == 2
    assert limiter.purge_idle(30) == 0
    assert limiter.locked("locked").allowed is False


async def test_wait_for_token_sleeps_until_allowed() -> None:
    clock = FakeClock()
    limiter = MemoryRateLimiter(clock)
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        clock.advance(seconds)

    for _ in range(3):
        await wait_for_token(limiter, "musicbrainz:global", ONE_PER_S, sleep)
    assert slept == [1, 1]


def test_backoff_reserves_one_attempt_per_window_and_success_resets_it() -> None:
    clock = FakeClock()
    limiter = MemoryRateLimiter(clock)
    assert limiter.failures("k") == 0
    delays = []
    for _ in range(6):
        assert limiter.reserve_backoff("k", base_s=1, max_s=10).allowed
        refused = limiter.reserve_backoff("k", base_s=1, max_s=10)
        assert not refused.allowed
        delays.append(refused.retry_after_s)
        clock.advance(refused.retry_after_s)
        assert limiter.locked("k").allowed
    assert delays == [1, 2, 4, 8, 10, 10]
    assert limiter.failures("k") == 6
    limiter.reserve_backoff("k", base_s=1, max_s=10)
    limiter.record_success("k")
    assert limiter.failures("k") == 0
    assert limiter.locked("k").allowed
    assert limiter.reserve_backoff("k", base_s=1, max_s=10).allowed
    assert limiter.locked("k") == Decision(False, 1)


@pytest.mark.parametrize(("base", "cap"), [(0.0, 1.0), (1.0, 0.0)])
def test_backoff_parameters_must_be_positive(base: float, cap: float) -> None:
    limiter = MemoryRateLimiter(FakeClock())
    with pytest.raises(ValueError, match="positive"):
        limiter.reserve_backoff("k", base_s=base, max_s=cap)
    assert limiter.failures("k") == 0


def test_peek_reports_tokens_without_taking_any() -> None:
    clock = FakeClock()
    limiter = MemoryRateLimiter(clock)
    limit = Limit(rate_per_s=1.0, burst=3)
    assert limiter.peek("k", limit) == 3
    limiter.hit("k", limit)
    limiter.hit("k", limit)
    assert limiter.peek("k", limit) == 1
    clock.advance(0.5)
    assert limiter.peek("k", limit) == 1.5
    clock.advance(3600)
    assert limiter.peek("k", limit) == 3
    assert [limiter.hit("k", limit).allowed for _ in range(4)] == [True, True, True, False]
