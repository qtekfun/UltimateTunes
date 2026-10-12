# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Token buckets, failure counting and lockout (100 % coverage required)."""

import pytest

from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.ratelimit import ALLOWED, Decision, Limit, SqliteRateLimiter, backoff_delay
from ultimatetunes.db import Database

LIMIT = Limit(rate_per_s=1.0, burst=3)


@pytest.fixture
def limiter(db: Database, clock: FakeClock) -> SqliteRateLimiter:
    return SqliteRateLimiter(db, clock)


def test_burst_then_refused_until_refill(limiter: SqliteRateLimiter, clock: FakeClock) -> None:
    assert [limiter.hit("ip:a", LIMIT).allowed for _ in range(3)] == [True, True, True]
    assert limiter.hit("ip:a", LIMIT) == Decision(allowed=False, retry_after_s=1)
    clock.advance(1.0)
    assert limiter.hit("ip:a", LIMIT) == ALLOWED
    assert not limiter.hit("ip:a", LIMIT).allowed


def test_refill_never_exceeds_the_burst(limiter: SqliteRateLimiter, clock: FakeClock) -> None:
    limiter.hit("ip:a", LIMIT)
    clock.advance(3600)
    assert [limiter.hit("ip:a", LIMIT).allowed for _ in range(4)] == [True, True, True, False]


def test_cost_larger_than_tokens_reports_the_wait(limiter: SqliteRateLimiter) -> None:
    slow = Limit(rate_per_s=0.5, burst=2)
    assert limiter.hit("yt", slow, cost=2).allowed
    assert limiter.hit("yt", slow, cost=2) == Decision(allowed=False, retry_after_s=4)


def test_keys_are_independent(limiter: SqliteRateLimiter) -> None:
    for _ in range(3):
        limiter.hit("ip:a", LIMIT)
    assert limiter.hit("ip:b", LIMIT).allowed


def test_failures_lock_the_key_until_the_lockout_ends(
    limiter: SqliteRateLimiter, clock: FakeClock
) -> None:
    assert limiter.record_failure("key:1", max_failures=2, lockout_s=60) == ALLOWED
    assert limiter.locked("key:1") == ALLOWED
    assert limiter.record_failure("key:1", max_failures=2, lockout_s=60) == Decision(False, 60)
    clock.advance(20)
    assert limiter.locked("key:1") == Decision(False, 40)
    assert limiter.hit("key:1", LIMIT) == Decision(False, 40)
    clock.advance(40)
    assert limiter.locked("key:1") == ALLOWED
    assert limiter.hit("key:1", LIMIT).allowed
    # The count started again after the lockout.
    assert limiter.record_failure("key:1", max_failures=2, lockout_s=60).allowed


def test_failure_only_bucket_starts_full(limiter: SqliteRateLimiter) -> None:
    limiter.record_failure("ip:c", max_failures=5, lockout_s=60)
    assert [limiter.hit("ip:c", LIMIT).allowed for _ in range(4)] == [True, True, True, False]


def test_success_clears_the_failure_count(limiter: SqliteRateLimiter) -> None:
    limiter.record_failure("key:1", max_failures=2, lockout_s=60)
    limiter.record_success("key:1")
    assert limiter.record_failure("key:1", max_failures=2, lockout_s=60).allowed
    limiter.record_success("unknown")


def test_unknown_key_is_not_locked(limiter: SqliteRateLimiter) -> None:
    assert limiter.locked("nobody") == ALLOWED


def test_purge_drops_idle_unlocked_buckets(limiter: SqliteRateLimiter, clock: FakeClock) -> None:
    limiter.hit("idle", LIMIT)
    limiter.record_failure("locked", max_failures=1, lockout_s=7200)
    clock.advance(3600)
    limiter.hit("fresh", LIMIT)
    assert limiter.purge_idle(1800) == 1
    assert limiter.locked("locked").allowed is False


@pytest.mark.parametrize(("rate", "burst"), [(0, 1), (1, 0), (-1, 1)])
def test_limits_must_be_positive(rate: float, burst: float) -> None:
    with pytest.raises(ValueError, match="positive"):
        Limit(rate, burst)


def test_failure_parameters_must_be_positive(limiter: SqliteRateLimiter) -> None:
    with pytest.raises(ValueError, match="positive"):
        limiter.record_failure("k", max_failures=0, lockout_s=1)
    with pytest.raises(ValueError, match="positive"):
        limiter.record_failure("k", max_failures=1, lockout_s=0)


def test_purging_never_wipes_a_live_failure_count(
    limiter: SqliteRateLimiter, clock: FakeClock
) -> None:
    """Slow brute force: 40 failures 200 s apart, with a purge of 600 s idle after each."""
    decisions = []
    for _ in range(40):
        clock.advance(200)
        decisions.append(limiter.record_failure("ip:slow", max_failures=40, lockout_s=900))
        assert limiter.purge_idle(600) == 0
    assert all(d.allowed for d in decisions[:-1])
    assert decisions[-1] == Decision(False, 900)
    assert limiter.locked("ip:slow") == Decision(False, 900)


def test_failures_are_forgotten_once_idle(limiter: SqliteRateLimiter, clock: FakeClock) -> None:
    limiter.record_failure("ip:gone", max_failures=2, lockout_s=60)
    clock.advance(601)
    assert limiter.purge_idle(600) == 1
    assert limiter.record_failure("ip:gone", max_failures=2, lockout_s=60).allowed


def test_success_and_hits_count_as_activity(limiter: SqliteRateLimiter, clock: FakeClock) -> None:
    limiter.record_failure("key:a", max_failures=5, lockout_s=60)
    limiter.hit("key:b", LIMIT)
    clock.advance(500)
    limiter.record_success("key:a")
    limiter.hit("key:b", LIMIT)
    clock.advance(500)
    assert limiter.purge_idle(600) == 0
    clock.advance(101)
    assert limiter.purge_idle(600) == 2


def test_backoff_doubles_up_to_the_cap(limiter: SqliteRateLimiter, clock: FakeClock) -> None:
    assert limiter.failures("user:a") == 0
    delays = []
    for _ in range(11):
        decision = limiter.record_failure_backoff("user:a", base_s=1, max_s=300)
        delays.append(decision.retry_after_s)
        assert limiter.locked("user:a") == Decision(False, decision.retry_after_s)
        clock.advance(decision.retry_after_s)
        assert limiter.locked("user:a") == ALLOWED
    assert delays == [1, 2, 4, 8, 16, 32, 64, 128, 256, 300, 300]
    # Never a hard lock: the count keeps growing, the delay stays at the cap.
    assert limiter.failures("user:a") == 11
    assert limiter.failures("user:b") == 0


def test_backoff_is_reset_by_a_success(limiter: SqliteRateLimiter, clock: FakeClock) -> None:
    for _ in range(4):
        limiter.record_failure_backoff("user:a", base_s=1, max_s=300)
    limiter.record_success("user:a")
    assert limiter.failures("user:a") == 0
    clock.advance(8)
    assert limiter.record_failure_backoff("user:a", base_s=1, max_s=300) == Decision(False, 1)


def test_backoff_keeps_the_tokens_of_the_bucket(limiter: SqliteRateLimiter) -> None:
    limiter.hit("user:a", LIMIT)
    limiter.record_failure_backoff("user:a", base_s=0.5, max_s=300)
    assert limiter.failures("user:a") == 1


@pytest.mark.parametrize(("base", "cap"), [(0.0, 1.0), (1.0, 0.0), (-1.0, 5.0)])
def test_backoff_parameters_must_be_positive(
    limiter: SqliteRateLimiter, base: float, cap: float
) -> None:
    with pytest.raises(ValueError, match="positive"):
        limiter.record_failure_backoff("user:a", base_s=base, max_s=cap)
    assert limiter.failures("user:a") == 0


def test_backoff_delay_never_overflows() -> None:
    assert backoff_delay(10**9, base_s=1, max_s=300) == 300
    assert backoff_delay(0, base_s=2, max_s=300) == 2
