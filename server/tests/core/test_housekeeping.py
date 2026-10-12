# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Housekeeping of the cache and the rate limiter (core/housekeeping.py, T22)."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import anyio
import anyio.from_thread
import pytest

from ultimatetunes.app import create_app
from ultimatetunes.core.cache import SqliteTtlCache
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.housekeeping import Housekeeping, Report, with_housekeeping
from ultimatetunes.core.ratelimit import Limit, SqliteRateLimiter
from ultimatetunes.db import Database
from ultimatetunes.settings import Settings

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def build(db: Database, clock: FakeClock, max_entries: int = 100) -> Housekeeping:
    return Housekeeping(
        SqliteTtlCache(db, clock),
        SqliteRateLimiter(db, clock),
        max_entries=max_entries,
        max_bytes=1_000_000,
    )


async def test_one_run_purges_trims_and_forgets_idle_buckets(
    db: Database, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    cache = SqliteTtlCache(db, clock)
    limiter = SqliteRateLimiter(db, clock)
    cache.set("gone", "v", ttl_s=1)
    limiter.hit("search:user:u1", Limit(1, 1))
    clock.advance(25 * 3600)
    for n in range(3):
        cache.set(f"k{n}", "v", ttl_s=100)
        clock.advance(1)
    housekeeping = Housekeeping(cache, limiter, max_entries=2, max_bytes=1_000_000)
    with caplog.at_level(logging.WARNING):
        assert housekeeping.run_once() == Report(expired=1, trimmed=1, idle_buckets=1)
    assert "size cap" in caplog.text
    assert cache.get("k0") is None
    assert build(db, clock).run_once() == Report(0, 0, 0)


class Boom(Housekeeping):
    def __init__(self) -> None:
        self.calls = 0
        self.twice = anyio.Event()

    def run_once(self) -> Report:
        self.calls += 1
        if self.calls == 2:
            anyio.from_thread.run_sync(self.twice.set)
        raise RuntimeError("database gone")


async def test_the_loop_survives_failures_and_stops_with_the_lifespan(
    caplog: pytest.LogCaptureFixture,
) -> None:
    boom = Boom()
    entered: list[str] = []

    @asynccontextmanager
    async def inner(_app: Any) -> AsyncIterator[str]:
        entered.append("in")
        yield "state"
        entered.append("out")

    lifespan = with_housekeeping(inner, boom, 0.01)
    with caplog.at_level(logging.ERROR):
        async with lifespan(None) as value:
            assert value == "state"
            with anyio.fail_after(5):
                await boom.twice.wait()
    assert entered == ["in", "out"]
    assert "housekeeping failed" in caplog.text


def test_the_app_runs_housekeeping_unless_turned_off(settings: Settings) -> None:
    on = create_app(settings).router.lifespan_context
    off = create_app(settings.model_copy(update={"housekeeping_interval_s": 0}))
    assert on.__qualname__.startswith("with_housekeeping.")
    assert not off.router.lifespan_context.__qualname__.startswith("with_housekeeping.")
