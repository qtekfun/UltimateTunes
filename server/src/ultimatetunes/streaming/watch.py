# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`JobWatch`: the latest worker report of each job that has listeners.

The api learns about growth from the worker's progress reports, never by polling the
filesystem (SPEC section 11). The reports land in the job row (`JobQueue.progress`); one
watcher task per job with listeners re-reads that row:

- at once when a report of that job reaches this process (`nudge`, called by the middleware
  of `web.py` after a successful `progress`, `complete` or `fail`);
- otherwise every `interval_s` (≤ 0.5 s), which covers reports handled by another api replica.

Listeners share the watcher: `current()` is the last view and the event that fires when the
next different view arrives, taken together so no change is missed between them.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress

from starlette.concurrency import run_in_threadpool

from ultimatetunes.jobs.queue import Job
from ultimatetunes.streaming.state import JobView

log = logging.getLogger(__name__)

ReadJob = Callable[[str], Job | None]


def view_of(job: Job | None) -> JobView | None:
    if job is None:
        return None
    return JobView(
        state=job.state,
        attempt_seq=job.attempt_seq,
        bytes_downloaded=job.bytes_downloaded or 0,
        expected_size=job.expected_size,
        part_path=job.part_path,
        final_path=job.final_path,
        finished=bool(job.finished),
        format_id=job.format_id,
        content_type=job.content_type,
        progressive=bool(job.progressive),
    )


class Watcher:
    """The shared view of one job."""

    def __init__(self, job_id: str, view: JobView | None) -> None:
        self.job_id = job_id
        self.view = view
        self.users = 0
        self.closed = False
        self.wake = asyncio.Event()
        self.task: asyncio.Task[None] | None = None
        self._changed = asyncio.Event()

    def current(self) -> tuple[JobView | None, asyncio.Event]:
        """The last view, and the event set when a different one arrives."""
        return self.view, self._changed

    def publish(self, view: JobView | None) -> None:
        if view == self.view:
            return
        self.view = view
        changed, self._changed = self._changed, asyncio.Event()
        changed.set()


class JobWatch:
    def __init__(self, read: ReadJob, *, interval_s: float) -> None:
        self._read = read
        self._interval_s = interval_s
        self._watchers: dict[str, Watcher] = {}

    async def _load(self, job_id: str) -> JobView | None:
        return view_of(await run_in_threadpool(self._read, job_id))

    async def _poll(self, watcher: Watcher) -> None:
        # Stopped by `closed`, never cancelled: a cancellation that lands while the timeout
        # fires could be taken for the timeout and swallowed.
        while True:
            with suppress(TimeoutError):
                async with asyncio.timeout(self._interval_s):
                    await watcher.wake.wait()
            if watcher.closed:
                return
            watcher.wake.clear()
            try:
                watcher.publish(await self._load(watcher.job_id))
            except Exception:  # the next round tries again; listeners keep the last view
                log.exception("reading job %s for its listeners failed", watcher.job_id)

    @asynccontextmanager
    async def watch(self, job_id: str) -> AsyncIterator[Watcher]:
        watcher = self._watchers.get(job_id)
        if watcher is None:
            watcher = Watcher(job_id, await self._load(job_id))
            # Another listener may have registered while this one was reading.
            watcher = self._watchers.setdefault(job_id, watcher)
        watcher.users += 1
        if watcher.task is None:
            watcher.task = asyncio.ensure_future(self._poll(watcher))
        try:
            yield watcher
        finally:
            watcher.users -= 1
            if watcher.users == 0:
                self._watchers.pop(job_id, None)
                watcher.closed = True
                watcher.wake.set()
                await watcher.task

    def nudge(self, job_id: str) -> None:
        """A report of `job_id` was stored: re-read it now."""
        watcher = self._watchers.get(job_id)
        if watcher is not None:
            watcher.wake.set()

    def watching(self, job_id: str) -> bool:
        return job_id in self._watchers
