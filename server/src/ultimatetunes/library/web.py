# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""App hook of the library area (`app.AREAS`). Owner: PLAN T05.

- `app.state.pending_streams`: the `PendingStreams` seam for songs without an archived file
  (`library.stream`). The library sets the default (`NotStreamingYet`); the streaming area
  (PLAN T16), installed later, replaces it.
- With `UT_LIBRARY_SCAN_ON_START` (default on), the app's lifespan scans `/music` in a
  background thread after startup (`app.state.library_scan`); shutdown stops the scan
  between two files and waits for it before the database closes.
"""

import logging
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from functools import lru_cache
from typing import Any

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from ultimatetunes.core.services import Services
from ultimatetunes.library.scan import LibraryScanner
from ultimatetunes.library.settings import LibrarySettings
from ultimatetunes.library.stream import NotStreamingYet

log = logging.getLogger(__name__)

Lifespan = Callable[[Any], AbstractAsyncContextManager[Any]]


@lru_cache(maxsize=1)
def library_settings() -> LibrarySettings:
    return LibrarySettings()


def _scan(services: Services, stop: threading.Event) -> None:
    try:
        LibraryScanner(services.db, services.library, services.clock).scan(stop=stop)
    except Exception:
        log.exception("library scan failed")


def with_startup_scan(inner: Lifespan, services: Services) -> Lifespan:
    @asynccontextmanager
    async def lifespan(app: Any) -> AsyncIterator[Any]:
        async with inner(app) as state:
            stop = threading.Event()
            worker = threading.Thread(
                target=_scan, args=(services, stop), name="library-scan", daemon=True
            )
            worker.start()
            app.state.library_scan = worker
            try:
                yield state
            finally:
                stop.set()
                await run_in_threadpool(worker.join)

    return lifespan


def install(app: FastAPI, services: Services) -> None:
    app.state.pending_streams = NotStreamingYet()
    if library_settings().library_scan_on_start:
        app.router.lifespan_context = with_startup_scan(app.router.lifespan_context, services)
