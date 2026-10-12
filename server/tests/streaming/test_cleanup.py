# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`StagingJanitor`: which staging directories go, and when (the api owns staging cleanup)."""

from pathlib import Path

import pytest

from tests.jobs.test_queue import add_track
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.inflight import MemoryInFlight
from ultimatetunes.core.storage import LocalStagingStore
from ultimatetunes.db import Database
from ultimatetunes.jobs.queue import SqliteJobQueue
from ultimatetunes.settings import Settings
from ultimatetunes.streaming.cleanup import StagingJanitor, listeners_key


class Setup:
    def __init__(self, db: Database, clock: FakeClock, root: Path) -> None:
        self.db = db
        self.clock = clock
        self.root = root
        self.jobs = SqliteJobQueue(db, clock)
        self.staging = LocalStagingStore(root)
        self.inflight = MemoryInFlight()
        self.janitor = StagingJanitor(self.jobs, self.staging, self.inflight)

    def job(self, track_id: str, video: str) -> str:
        add_track(self.db, self.clock, track_id, video)
        return self.jobs.enqueue(track_id=track_id, video_id=video, priority=100).id

    def claim(self) -> str:
        claimed = self.jobs.claim("w1", lease_s=60)
        assert claimed is not None
        self.file(f"{claimed.job.staging_dir}/x.webm")
        return claimed.lease.lease_id

    def file(self, rel: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    def state(self, job_id: str, state: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE jobs SET state = ?, lease_id = NULL, lease_expires_at = NULL WHERE id = ?",
                (state, job_id),
            )

    def exists(self, rel: str) -> bool:
        return (self.root / rel).exists()


@pytest.fixture
def setup(settings: Settings, db: Database, clock: FakeClock) -> Setup:
    return Setup(db, clock, settings.staging_dir)


def test_a_leased_attempt_is_kept_and_older_ones_go(setup: Setup) -> None:
    job = setup.job("t1", "Rb8Tn3ZcYv0")
    lease = setup.claim()
    setup.jobs.fail(job, lease, error_code="network_error", retryable=True, message="x")
    setup.clock.advance(3600)
    setup.claim()
    assert setup.exists(f"{job}/1")
    assert setup.janitor.clean_job(job) == 1
    assert not setup.exists(f"{job}/1")
    assert setup.exists(f"{job}/2")


@pytest.mark.anyio
async def test_nothing_goes_while_someone_listens(setup: Setup) -> None:
    job = setup.job("t1", "Rb8Tn3ZcYv0")
    setup.claim()
    setup.state(job, "ready")
    async with setup.inflight.listen(listeners_key(job)):
        assert setup.janitor.clean_job(job) == 0
        assert setup.janitor.sweep() == 0
        assert setup.exists(f"{job}/1")
    assert setup.janitor.clean_job(job) == 1
    assert not setup.exists(job)


def test_an_unknown_job_is_left_to_the_sweep(setup: Setup) -> None:
    setup.file("0199d6a2-4c1e-7b3a-9f10-2a6c8e019999/1/x.webm")
    assert setup.janitor.clean_job("0199d6a2-4c1e-7b3a-9f10-2a6c8e019999") == 0
    assert setup.janitor.sweep() == 1
    assert not setup.exists("0199d6a2-4c1e-7b3a-9f10-2a6c8e019999")


def test_the_sweep_cleans_what_nobody_needs(setup: Setup) -> None:
    ready = setup.job("t1", "Rb8Tn3ZcYv0")
    setup.claim()
    setup.state(ready, "ready")
    failed = setup.job("t2", "Wq5Jd7HsKe2")
    setup.claim()
    setup.state(failed, "failed")
    running = setup.job("t3", "Qx7Lm2pZ0aB")
    setup.claim()
    setup.file("stray.txt")  # not a job directory: untouched
    setup.file(f"{running}/notes.txt")  # not an attempt directory: untouched
    assert setup.janitor.sweep() == 2
    assert not setup.exists(ready)
    assert not setup.exists(f"{failed}/1")
    assert setup.exists(f"{running}/1/x.webm")
    assert setup.exists("stray.txt")
    assert setup.exists(f"{running}/notes.txt")


def test_a_failed_delete_is_logged_and_skipped(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    job = setup.job("t1", "Rb8Tn3ZcYv0")
    setup.claim()
    setup.state(job, "failed")

    def broken(rel: str) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(setup.staging, "delete", broken)
    assert setup.janitor.clean_job(job) == 0
    assert "staging cleanup" in caplog.text
