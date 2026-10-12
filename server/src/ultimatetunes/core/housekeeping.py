# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Periodic housekeeping of the api's shared state (SECURITY.md, T22).

Every `UT_HOUSEKEEPING_INTERVAL_S` (10 min; 0 turns it off) the api:
- removes expired `TtlCache` entries, then trims the cache to `UT_CACHE_MAX_ENTRIES` and
  `UT_CACHE_MAX_BYTES` (oldest first), so search and catalog results cannot fill `/data`;
- forgets rate-limit buckets idle for a day (a running lockout is never dropped).

Every step is idempotent, so several replicas may run it at once. The first run comes one
interval after start, never during start-up.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from dataclasses import dataclass
from typing import Any

import anyio
from starlette.concurrency import run_in_threadpool

from ultimatetunes.core.cache import TtlCache
from ultimatetunes.core.ratelimit import RateLimiter

log = logging.getLogger(__name__)

RATE_LIMIT_IDLE_S = 24 * 3600.0
Lifespan = Callable[[Any], AbstractAsyncContextManager[Any]]


@dataclass(frozen=True)
class Report:
    expired: int
    trimmed: int
    idle_buckets: int


class Housekeeping:
    def __init__(
        self, cache: TtlCache, limiter: RateLimiter, *, max_entries: int, max_bytes: int
    ) -> None:
        self._cache = cache
        self._limiter = limiter
        self._max_entries = max_entries
        self._max_bytes = max_bytes

    def run_once(self) -> Report:
        report = Report(
            expired=self._cache.purge_expired(),
            trimmed=self._cache.trim(self._max_entries, self._max_bytes),
            idle_buckets=self._limiter.purge_idle(RATE_LIMIT_IDLE_S),
        )
        if report.trimmed:
            log.warning("the cache reached its size cap: %d oldest entries removed", report.trimmed)
        return report

    async def run_forever(self, interval_s: float) -> None:
        while True:
            await anyio.sleep(interval_s)
            try:
                await run_in_threadpool(self.run_once)
            except Exception:
                log.exception("housekeeping failed")


def with_housekeeping(inner: Lifespan, housekeeping: Housekeeping, interval_s: float) -> Lifespan:
    """Wraps an app lifespan so housekeeping runs while the app serves."""

    @asynccontextmanager
    async def lifespan(app: Any) -> AsyncIterator[Any]:
        async with inner(app) as value:
            task = asyncio.ensure_future(housekeeping.run_forever(interval_s))
            try:
                yield value
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    return lifespan
