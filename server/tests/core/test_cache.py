# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""TtlCache: the SQLite implementation and the in-memory fake behave the same."""

from collections.abc import Callable

import pytest

from ultimatetunes.core.cache import (
    MemoryTtlCache,
    SqliteTtlCache,
    TtlCache,
    get_json,
    set_json,
)
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.db import Database

Factory = Callable[[Database, FakeClock], TtlCache]
FACTORIES: list[Factory] = [SqliteTtlCache, lambda _db, clock: MemoryTtlCache(clock)]


@pytest.fixture(params=FACTORIES, ids=["sqlite", "memory"])
def cache(request: pytest.FixtureRequest, db: Database, clock: FakeClock) -> TtlCache:
    factory: Factory = request.param
    return factory(db, clock)


def test_values_expire(cache: TtlCache, clock: FakeClock) -> None:
    assert cache.get("k") is None
    cache.set("k", "v1", ttl_s=10)
    assert cache.get("k") == "v1"
    cache.set("k", "v2", ttl_s=10)
    assert cache.get("k") == "v2"
    clock.advance(10)
    assert cache.get("k") is None


def test_delete_and_purge(cache: TtlCache, clock: FakeClock) -> None:
    cache.set("short", "a", ttl_s=1)
    cache.set("long", "b", ttl_s=100)
    cache.delete("long")
    cache.delete("missing")
    assert cache.get("long") is None
    cache.set("long", "b", ttl_s=100)
    clock.advance(5)
    assert cache.purge_expired() == 1
    assert cache.get("long") == "b"


def test_json_helpers(cache: TtlCache) -> None:
    assert get_json(cache, "j") is None
    set_json(cache, "j", {"title": "Glass Orchard", "n": [1, 2]}, ttl_s=60)
    assert get_json(cache, "j") == {"title": "Glass Orchard", "n": [1, 2]}


def test_ttl_must_be_positive(cache: TtlCache) -> None:
    with pytest.raises(ValueError, match="ttl"):
        cache.set("k", "v", ttl_s=0)


def test_trim_removes_the_oldest_entries_past_the_entry_cap(
    cache: TtlCache, clock: FakeClock
) -> None:
    for n in range(5):
        cache.set(f"k{n}", "v", ttl_s=100)
        clock.advance(1)
    cache.set("k0", "renewed", ttl_s=100)  # a rewrite makes the entry young again
    assert cache.trim(max_entries=3, max_bytes=10_000) == 2
    assert [cache.get(f"k{n}") for n in range(5)] == [
        "renewed",
        None,
        None,
        "v",
        "v",
    ]
    assert cache.trim(max_entries=3, max_bytes=10_000) == 0


def test_trim_keeps_the_total_size_under_the_byte_cap(cache: TtlCache, clock: FakeClock) -> None:
    for n in range(4):
        cache.set(f"k{n}", "x" * 100, ttl_s=100)
        clock.advance(1)
    assert cache.trim(max_entries=1000, max_bytes=250) == 2
    assert cache.get("k1") is None
    assert cache.get("k2") == "x" * 100


def test_trim_works_in_batches(db: Database, clock: FakeClock) -> None:
    cache = SqliteTtlCache(db, clock)
    with db.transaction() as conn:
        for n in range(1200):
            conn.execute(
                "INSERT INTO cache_entries (key, value, expires_at, created_at)"
                " VALUES (?, 'v', '2999-01-01T00:00:00.000Z', ?)",
                (f"k{n:05d}", f"2026-01-01T00:00:{n % 60:02d}.{n // 60:03d}Z"),
            )
    assert cache.trim(max_entries=100, max_bytes=10_000_000) == 1100
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM cache_entries").scalar() == 100
