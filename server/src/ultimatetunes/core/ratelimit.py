# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`RateLimiter`: token buckets plus a failure counter with temporary lockout.

One bucket per key (`auth:ip:192.0.2.10`, `auth:key:<id>`, `ytmusic:global`). Callers choose
the limits; this module only does the arithmetic and keeps the state in `rate_limit_buckets`
(SQLite in v1, Redis in phase 5 behind the same protocol). 100 % test coverage (CLAUDE.md).

- `hit(key, limit)` takes `cost` tokens, or refuses with the seconds until enough refill.
  A locked key is refused until the lockout ends.
- `record_failure(key, ...)` counts a failure (wrong password, invalid key); reaching
  `max_failures` locks the key for `lockout_s` and starts a new count.
- `record_success(key)` clears the failure count.
- `peek(key, limit)` says how many tokens `key` holds now (a full bucket when unknown), without
  taking any or touching the key (the admin panel's view of a budget).
- `purge_idle(idle_s)` forgets keys with no activity (hit, failure or success) for `idle_s`
  and no running lockout. So a failure count lives as long as failures keep coming less than
  `idle_s` apart: purging never wipes a live count.
"""

import math
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from ultimatetunes.core.clock import Clock, format_ts, parse_ts
from ultimatetunes.db.database import Database
from ultimatetunes.db.driver import Connection


@dataclass(frozen=True)
class Limit:
    rate_per_s: float
    burst: float

    def __post_init__(self) -> None:
        if self.rate_per_s <= 0 or self.burst <= 0:
            raise ValueError("rate and burst must be positive")


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after_s: int = 0


ALLOWED = Decision(allowed=True)
_FULL = 1e9


class RateLimiter(Protocol):
    def hit(self, key: str, limit: Limit, cost: float = 1.0) -> Decision: ...

    def locked(self, key: str) -> Decision:
        """Refused while the key is locked out; does not take tokens."""
        ...

    def record_failure(self, key: str, *, max_failures: int, lockout_s: float) -> Decision:
        """Refused when this failure locked the key."""
        ...

    def record_success(self, key: str) -> None: ...

    def peek(self, key: str, limit: Limit) -> float:
        """Tokens `key` holds now under `limit` (the burst when unknown); changes nothing."""
        ...

    def purge_idle(self, idle_s: float) -> int:
        """Drops keys with no activity for `idle_s` and not locked. Returns how many."""
        ...


def _ceil_s(seconds: float) -> int:
    return max(1, math.ceil(seconds))


@dataclass
class _Bucket:
    tokens: float
    # Refill time of the tokens.
    updated_at: str
    failures: int
    locked_until: str | None


class SqliteRateLimiter:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    def _load(self, conn: Connection, key: str) -> _Bucket | None:
        row = conn.execute(
            "SELECT tokens, updated_at, failures, locked_until FROM rate_limit_buckets"
            " WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        locked = row["locked_until"]
        return _Bucket(
            tokens=float(str(row["tokens"])),
            updated_at=str(row["updated_at"]),
            failures=int(str(row["failures"])),
            locked_until=None if locked is None else str(locked),
        )

    def _save(self, conn: Connection, key: str, bucket: _Bucket) -> None:
        conn.execute(
            "INSERT INTO rate_limit_buckets"
            " (key, tokens, updated_at, touched_at, failures, locked_until)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (key) DO UPDATE SET tokens = excluded.tokens,"
            " updated_at = excluded.updated_at, touched_at = excluded.touched_at,"
            " failures = excluded.failures, locked_until = excluded.locked_until",
            (
                key,
                bucket.tokens,
                bucket.updated_at,
                format_ts(self._clock.now()),
                bucket.failures,
                bucket.locked_until,
            ),
        )

    def _lockout(self, bucket: _Bucket | None) -> Decision:
        if bucket is None or bucket.locked_until is None:
            return ALLOWED
        remaining = (parse_ts(bucket.locked_until) - self._clock.now()).total_seconds()
        return (
            Decision(allowed=False, retry_after_s=_ceil_s(remaining)) if remaining > 0 else ALLOWED
        )

    def hit(self, key: str, limit: Limit, cost: float = 1.0) -> Decision:
        now = self._clock.now()
        with self._db.transaction() as conn:
            bucket = self._load(conn, key)
            locked = self._lockout(bucket)
            if not locked.allowed:
                return locked
            if bucket is None:
                bucket = _Bucket(limit.burst, format_ts(now), 0, None)
            else:
                elapsed = max(0.0, (now - parse_ts(bucket.updated_at)).total_seconds())
                bucket.tokens = min(limit.burst, bucket.tokens + elapsed * limit.rate_per_s)
                bucket.updated_at = format_ts(now)
            if bucket.tokens >= cost:
                bucket.tokens -= cost
                decision = ALLOWED
            else:
                wait = (cost - bucket.tokens) / limit.rate_per_s
                decision = Decision(allowed=False, retry_after_s=_ceil_s(wait))
            self._save(conn, key, bucket)
        return decision

    def locked(self, key: str) -> Decision:
        with self._db.read() as conn:
            return self._lockout(self._load(conn, key))

    def peek(self, key: str, limit: Limit) -> float:
        with self._db.read() as conn:
            bucket = self._load(conn, key)
        if bucket is None:
            return limit.burst
        elapsed = max(0.0, (self._clock.now() - parse_ts(bucket.updated_at)).total_seconds())
        return min(limit.burst, bucket.tokens + elapsed * limit.rate_per_s)

    def record_failure(self, key: str, *, max_failures: int, lockout_s: float) -> Decision:
        if max_failures < 1 or lockout_s <= 0:
            raise ValueError("max_failures and lockout_s must be positive")
        now = self._clock.now()
        with self._db.transaction() as conn:
            # A new bucket starts full: the next `hit` caps the tokens to that limit's burst.
            bucket = self._load(conn, key) or _Bucket(_FULL, format_ts(now), 0, None)
            bucket.failures += 1
            decision = ALLOWED
            if bucket.failures >= max_failures:
                bucket.failures = 0
                bucket.locked_until = format_ts(now + timedelta(seconds=lockout_s))
                decision = Decision(allowed=False, retry_after_s=_ceil_s(lockout_s))
            self._save(conn, key, bucket)
        return decision

    def record_success(self, key: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE rate_limit_buckets SET failures = 0, touched_at = ? WHERE key = ?",
                (format_ts(self._clock.now()), key),
            )

    def purge_idle(self, idle_s: float) -> int:
        now = self._clock.now()
        cutoff = format_ts(now - timedelta(seconds=idle_s))
        with self._db.transaction() as conn:
            return conn.execute(
                "DELETE FROM rate_limit_buckets WHERE touched_at < ?"
                " AND (locked_until IS NULL OR locked_until <= ?)",
                (cutoff, format_ts(now)),
            ).rowcount
