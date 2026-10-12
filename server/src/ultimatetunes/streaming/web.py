# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""App hook of the streaming area (`app.AREAS`). Owner: PLAN T16.

- `app.state.pending_streams`: replaces the library's default (`NotStreamingYet`) with
  `StreamingWhileDownloading`, so `/ut/v1/server` announces `streamingWhileDownloading`.
- `ReportListener` middleware: after a successful worker `progress`, `complete` or `fail` of a
  job, wakes that job's listeners at once (`JobWatch.nudge`); after `complete`/`fail` of a job
  nobody streams, cleans its staging directories.
- With `UT_STAGING_SWEEP_INTERVAL_S` > 0, the lifespan sweeps `/staging` at start and then
  periodically (`StagingJanitor.sweep`).
"""

import asyncio
import logging
import re
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from typing import Any

import anyio
from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ultimatetunes.core.services import Services
from ultimatetunes.streaming.cleanup import StagingJanitor
from ultimatetunes.streaming.service import StreamingWhileDownloading
from ultimatetunes.streaming.settings import StreamingSettings
from ultimatetunes.streaming.watch import JobWatch

log = logging.getLogger(__name__)

Lifespan = Callable[[Any], AbstractAsyncContextManager[Any]]
_REPORT = re.compile(r"^/internal/v1/jobs/([^/]{1,64})/(progress|complete|fail)$")
_OK = 200


class ReportListener:
    """A plain ASGI middleware: every other request passes through untouched."""

    def __init__(self, app: ASGIApp, *, watch: JobWatch, janitor: StagingJanitor) -> None:
        self.app = app
        self.watch = watch
        self.janitor = janitor

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        match = None
        if scope["type"] == "http" and scope["method"] == "POST":
            match = _REPORT.match(scope["path"])
        if match is None:
            await self.app(scope, receive, send)
            return
        status = 0

        async def capture(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        await self.app(scope, receive, capture)
        if status != _OK:
            return
        job_id, call = match.groups()
        self.watch.nudge(job_id)
        if call != "progress" and not self.watch.watching(job_id):
            await clean(self.janitor, job_id)


async def clean(janitor: StagingJanitor, job_id: str) -> None:
    try:
        await run_in_threadpool(janitor.clean_job, job_id)
    except Exception:
        log.exception("staging cleanup of job %s failed", job_id)


async def sweep_forever(janitor: StagingJanitor, interval_s: float) -> None:
    while True:
        try:
            await run_in_threadpool(janitor.sweep)
        except Exception:
            log.exception("staging sweep failed")
        await anyio.sleep(interval_s)


def with_sweeper(inner: Lifespan, janitor: StagingJanitor, interval_s: float) -> Lifespan:
    @asynccontextmanager
    async def lifespan(app: Any) -> AsyncIterator[Any]:
        async with inner(app) as state:
            task = asyncio.ensure_future(sweep_forever(janitor, interval_s))
            try:
                yield state
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    return lifespan


def install(app: FastAPI, services: Services) -> None:
    settings = StreamingSettings()
    watch = JobWatch(services.jobs.get, interval_s=settings.stream_poll_interval_s)
    janitor = StagingJanitor(services.jobs, services.staging, services.inflight)
    app.state.pending_streams = StreamingWhileDownloading(services, settings, watch, janitor)
    app.state.staging_janitor = janitor
    app.add_middleware(ReportListener, watch=watch, janitor=janitor)
    if settings.staging_sweep_interval_s > 0:
        app.router.lifespan_context = with_sweeper(
            app.router.lifespan_context, janitor, settings.staging_sweep_interval_s
        )
