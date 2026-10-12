# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`TtlCache`: text values with a time to live.

The v1 implementation is `SqliteTtlCache` on the `cache_entries` table: disk over RAM, so a
large search or catalog cache costs no memory (the author's footprint target, SPEC §6).
`MemoryTtlCache` is the fake for tests. Values are application-encoded text; `get_json` and
`set_json` cover the common case. Expired entries are ignored on read; the api's housekeeping
(`core/housekeeping.py`) calls `purge_expired()` and then `trim()` with the size caps
(`UT_CACHE_MAX_ENTRIES`, `UT_CACHE_MAX_BYTES`), so the cache cannot fill `/data` (T22).
"""

import json
from datetime import timedelta
from typing import Protocol

from ultimatetunes.core.clock import Clock, format_ts
from ultimatetunes.db.database import Database


class TtlCache(Protocol):
    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str, ttl_s: float) -> None: ...

    def delete(self, key: str) -> None: ...

    def purge_expired(self) -> int:
        """Removes expired entries and returns how many."""
        ...

    def trim(self, max_entries: int, max_bytes: int) -> int:
        """Removes the oldest entries (by creation) until at most `max_entries` remain and
        their values add up to at most `max_bytes` (UTF-8 bytes in the fake, characters in
        SQL, which is close enough for a cap). Returns how many were removed."""
        ...


def get_json(cache: TtlCache, key: str) -> object | None:
    raw = cache.get(key)
    return None if raw is None else json.loads(raw)


def set_json(cache: TtlCache, key: str, value: object, ttl_s: float) -> None:
    cache.set(key, json.dumps(value, separators=(",", ":"), ensure_ascii=False), ttl_s)


def _check_ttl(ttl_s: float) -> None:
    if ttl_s <= 0:
        raise ValueError("ttl must be positive")


_DELETE_BATCH = 500


class SqliteTtlCache:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    def get(self, key: str) -> str | None:
        now = format_ts(self._clock.now())
        with self._db.read() as conn:
            value = conn.execute(
                "SELECT value FROM cache_entries WHERE key = ? AND expires_at > ?", (key, now)
            ).scalar()
        return None if value is None else str(value)

    def set(self, key: str, value: str, ttl_s: float) -> None:
        _check_ttl(ttl_s)
        now = self._clock.now()
        expires = format_ts(now + timedelta(seconds=ttl_s))
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO cache_entries (key, value, expires_at, created_at)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT (key) DO UPDATE SET value = excluded.value,"
                " expires_at = excluded.expires_at, created_at = excluded.created_at",
                (key, value, expires, format_ts(now)),
            )

    def delete(self, key: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM cache_entries WHERE key = ?", (key,))

    def purge_expired(self) -> int:
        now = format_ts(self._clock.now())
        with self._db.transaction() as conn:
            return conn.execute("DELETE FROM cache_entries WHERE expires_at <= ?", (now,)).rowcount

    def trim(self, max_entries: int, max_bytes: int) -> int:
        removed = 0
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(LENGTH(value)), 0) AS size FROM cache_entries"
            ).fetchone()
            count, size = (_int(row["n"]), _int(row["size"])) if row is not None else (0, 0)
            while count > max_entries or size > max_bytes:
                oldest = conn.execute(
                    "SELECT key, LENGTH(value) AS size FROM cache_entries"
                    " ORDER BY created_at, key LIMIT ?",
                    (_DELETE_BATCH,),
                ).fetchall()
                doomed: list[str] = []
                for entry in oldest:
                    if count <= max_entries and size <= max_bytes:
                        break
                    doomed.append(str(entry["key"]))
                    count -= 1
                    size -= _int(entry["size"])
                if not doomed:  # pragma: no cover - the counts above say rows exist
                    break
                # Only "?" placeholders are formatted in; the keys travel as parameters.
                marks = ", ".join("?" * len(doomed))
                conn.execute(
                    f"DELETE FROM cache_entries WHERE key IN ({marks})",  # noqa: S608  # nosec B608
                    tuple(doomed),
                )
                removed += len(doomed)
        return removed


def _int(value: object) -> int:
    return int(str(value)) if value is not None else 0


class MemoryTtlCache:
    """In-memory fake with the same semantics, for tests."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        # Insertion order is creation order (a `set` moves the key to the end).
        self._entries: dict[str, tuple[str, float]] = {}

    def get(self, key: str) -> str | None:
        entry = self._entries.get(key)
        if entry is None or entry[1] <= self._clock.monotonic():
            return None
        return entry[0]

    def set(self, key: str, value: str, ttl_s: float) -> None:
        _check_ttl(ttl_s)
        self._entries.pop(key, None)
        self._entries[key] = (value, self._clock.monotonic() + ttl_s)

    def delete(self, key: str) -> None:
        self._entries.pop(key, None)

    def purge_expired(self) -> int:
        now = self._clock.monotonic()
        expired = [k for k, (_, until) in self._entries.items() if until <= now]
        for key in expired:
            del self._entries[key]
        return len(expired)

    def trim(self, max_entries: int, max_bytes: int) -> int:
        size = sum(len(value.encode()) for value, _ in self._entries.values())
        removed = 0
        while self._entries and (len(self._entries) > max_entries or size > max_bytes):
            key = next(iter(self._entries))
            size -= len(self._entries.pop(key)[0].encode())
            removed += 1
        return removed
