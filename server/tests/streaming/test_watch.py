# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`JobWatch`: one watcher per job with listeners, woken by reports, polling as a fallback."""

from dataclasses import replace

import anyio
import pytest

from tests.jobs.test_queue import add_track
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.db import Database
from ultimatetunes.jobs.queue import Job, SqliteJobQueue
from ultimatetunes.streaming.state import JobView
from ultimatetunes.streaming.watch import JobWatch, view_of

pytestmark = pytest.mark.anyio


@pytest.fixture
def job(db: Database, clock: FakeClock) -> Job:
    add_track(db, clock, "t1", "Rb8Tn3ZcYv0")
    return SqliteJobQueue(db, clock).enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)


class Reads:
    def __init__(self, job: Job) -> None:
        self.job: Job | None = job
        self.calls = 0
        self.fail_next = False

    def __call__(self, job_id: str) -> Job | None:
        self.calls += 1
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("database is locked")
        return self.job


def test_view_of_a_job(job: Job) -> None:
    assert view_of(None) is None
    view = view_of(job)
    assert view == JobView(state="queued", attempt_seq=0)


async def test_a_nudge_rereads_at_once(job: Job) -> None:
    reads = Reads(job)
    watch = JobWatch(reads, interval_s=30)
    async with watch.watch(job.id) as watcher:
        assert watch.watching(job.id)
        view, changed = watcher.current()
        assert view is not None
        assert view.state == "queued"
        reads.job = replace(job, state="downloading", attempt_seq=1)
        watch.nudge(job.id)
        watch.nudge("another-job")  # nobody watches it: nothing happens
        with anyio.fail_after(2):
            await changed.wait()
        view, _ = watcher.current()
        assert view is not None
        assert view.state == "downloading"
    assert not watch.watching(job.id)


async def test_it_polls_without_reports_and_survives_a_failed_read(
    job: Job, caplog: pytest.LogCaptureFixture
) -> None:
    reads = Reads(job)
    watch = JobWatch(reads, interval_s=0.01)
    async with watch.watch(job.id) as watcher:
        reads.fail_next = True
        with anyio.fail_after(2):
            while reads.calls < 4:  # noqa: ASYNC110 - counts the watcher's own reads
                await anyio.sleep(0.01)
        _, changed = watcher.current()
        reads.job = None  # the job vanished
        with anyio.fail_after(2):
            await changed.wait()
        assert watcher.current()[0] is None
    assert "reading job" in caplog.text


async def test_listeners_share_one_watcher(job: Job) -> None:
    reads = Reads(job)
    watch = JobWatch(reads, interval_s=30)
    async with watch.watch(job.id) as first, watch.watch(job.id) as second:
        assert first is second
        assert first.users == 2
        assert reads.calls == 1
    assert not watch.watching(job.id)


async def test_an_unchanged_view_wakes_nobody(job: Job) -> None:
    reads = Reads(job)
    watch = JobWatch(reads, interval_s=30)
    async with watch.watch(job.id) as watcher:
        _, changed = watcher.current()
        watcher.publish(view_of(job))
        assert not changed.is_set()
