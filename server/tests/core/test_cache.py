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
