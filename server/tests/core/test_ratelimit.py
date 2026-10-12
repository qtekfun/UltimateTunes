# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Token buckets, failure counting and lockout (100 % coverage required)."""

import pytest

from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.ratelimit import ALLOWED, Decision, Limit, SqliteRateLimiter
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
