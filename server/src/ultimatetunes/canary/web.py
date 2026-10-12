# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""App hook of the canary (`app.AREAS`). Owner: PLAN T19.

Runs `ApiCanary` inside the app's lifespan (wrapped here, like the admin's notification
sweep, so `app.py` stays untouched): after `UT_CANARY_FIRST_DELAY_S`, every
`UT_CANARY_POLL_S` it asks `CanaryStore.claim` whether the catalog checks are due (daily by
default, or right after an admin's "run the canary now") and, if this replica won the claim,
runs them and records the result. Failed runs reach the admin's notification target through
the notification sweep (T15).

The catalog is ytmusicapi **without** the api's cache and rate-limit guard (a cached answer
would hide a breakage), or the services' fake catalog with `UT_FAKE_YOUTUBE` (test stack).
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

import anyio
from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from ultimatetunes.canary.checks import CatalogCanary, Report, targets
from ultimatetunes.canary.settings import CanarySettings
from ultimatetunes.canary.store import CanaryStore
from ultimatetunes.core.services import Services
from ultimatetunes.db.driver import DatabaseError
from ultimatetunes.search.catalog import MusicCatalog

log = logging.getLogger(__name__)

CatalogFactory = Callable[[], MusicCatalog]


def canary_catalog(services: Services) -> MusicCatalog:
    """The catalog the canary asks: the fake one on the test stack, else bare ytmusicapi."""
    if services.settings.fake_youtube:
        return services.catalog
    from ultimatetunes.search.settings import SearchSettings  # noqa: PLC0415 - api role only
    from ultimatetunes.search.ytmusic import YTMusicCatalog  # noqa: PLC0415

    return YTMusicCatalog.build(SearchSettings())


class ApiCanary:
    def __init__(
        self,
        services: Services,
        settings: CanarySettings,
        catalog: CatalogFactory | None = None,
    ) -> None:
        self._services = services
        self._settings = settings
        self._catalog = catalog or (lambda: canary_catalog(services))
        self._store = CanaryStore(services.db, services.clock)

    @property
    def interval(self) -> timedelta:
        return timedelta(hours=self._settings.canary_interval_h)

    async def run_once(self) -> Report | None:
        """The catalog checks if due and claimed by this replica; their report, or None."""
        claimed = await run_in_threadpool(
            self._store.claim, self.interval, scheduled=self._settings.canary_enabled
        )
        if not claimed:
            return None
        return await self.run_now()

    async def run_now(self) -> Report:
        s = self._settings
        target = targets(
            self._services.settings, s.canary_video_id, s.canary_query, s.canary_playlist_id
        )
        canary = CatalogCanary(self._catalog(), target, self._services.clock, s.canary_timeout_s)
        report = await canary.run()
        await run_in_threadpool(self._store.record, report)
        if report.ok:
            log.info("canary (catalog): ok")
        else:
            log.warning("canary (catalog) failed: %s", report.message)
        return report

    async def run_forever(self) -> None:
        await anyio.sleep(self._settings.canary_first_delay_s)
        while True:
            try:
                await self.run_once()
            except DatabaseError as exc:
                log.warning("canary: database unavailable: %s", exc)
            await anyio.sleep(self._settings.canary_poll_s)


def install(app: FastAPI, services: Services, settings: CanarySettings | None = None) -> None:
    canary = ApiCanary(services, settings or CanarySettings())
    inner = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(target: Any) -> AsyncIterator[Any]:
        async with inner(target) as value:
            task = asyncio.create_task(canary.run_forever())
            try:
                yield value
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    app.router.lifespan_context = lifespan
