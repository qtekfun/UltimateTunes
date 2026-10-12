# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""JobQueue on SQLite: deduplication, leases, heartbeats and lease expiry."""

from typing import Any

import pytest

from ultimatetunes.core.clock import FakeClock, format_ts
from ultimatetunes.db import Database
from ultimatetunes.db.driver import Connection
from ultimatetunes.errors import InvalidStateTransition, LeaseLost, NotFound, PathRejected
from ultimatetunes.jobs.queue import (
    PRIORITY_KEEP,
    PRIORITY_STREAM,
    Claimed,
    Job,
    JobResult,
    ProgressReport,
    SqliteJobQueue,
)


def add_track(db: Database, clock: FakeClock, track_id: str, video_id: str) -> None:
    now = format_ts(clock.now())
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO tracks (id, status, title, title_norm, artist_name, yt_video_id,"
            " created_at, updated_at) VALUES (?, 'pending', 'Glass Orchard', 'glass orchard',"
            " 'The Paper Lanterns', ?, ?, ?)",
            (track_id, video_id, now, now),
        )


def report(claimed: Claimed, **changes: Any) -> ProgressReport:
    """A valid progress report of the claimed attempt, with `changes` applied."""
    base = claimed.job.staging_dir
    fields: dict[str, Any] = {
        "state": "downloading",
        "progress": 0.5,
        "bytes_downloaded": 100,
        "expected_size": 200,
        "part_path": f"{base}/Rb8Tn3ZcYv0.webm.part",
        "final_path": f"{base}/Rb8Tn3ZcYv0.webm",
        "finished": False,
        "format_id": "251",
        "content_type": "audio/webm",
        "progressive": True,
    }
    fields.update(changes)
    return ProgressReport(**fields)


def to_tagging(queue: SqliteJobQueue, claimed: Claimed) -> None:
    queue.progress(
        claimed.job.id,
        claimed.lease.lease_id,
        report(claimed, state="tagging", bytes_downloaded=200, progress=1.0, finished=True),
    )


@pytest.fixture
def queue(db: Database, clock: FakeClock) -> SqliteJobQueue:
    add_track(db, clock, "t1", "Rb8Tn3ZcYv0")
    add_track(db, clock, "t2", "Wq5Jd7HsKe2")
    return SqliteJobQueue(db, clock)


def test_enqueue_deduplicates_per_track_and_raises_priority(queue: SqliteJobQueue) -> None:
    first = queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=PRIORITY_KEEP)
    again = queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=PRIORITY_STREAM)
    assert again.id == first.id
    assert again.priority == PRIORITY_STREAM
    lower = queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    assert lower.priority == PRIORITY_STREAM
    assert queue.get(first.id) == lower
    assert queue.get("nope") is None


def test_claim_takes_highest_priority_with_a_lease(queue: SqliteJobQueue, clock: FakeClock) -> None:
    low = queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=PRIORITY_KEEP)
    high = queue.enqueue(track_id="t2", video_id="Wq5Jd7HsKe2", priority=PRIORITY_STREAM)
    claimed = queue.claim("w1", lease_s=60)
    assert claimed is not None
    assert claimed.job.id == high.id
    assert claimed.job.state == "downloading"
    assert claimed.job.attempts == 1
    assert claimed.lease.heartbeat_s == 20
    assert claimed.lease.expires_at == "2026-10-12T08:01:00.000Z"
    second = queue.claim("w2", lease_s=60)
    assert second is not None
    assert second.job.id == low.id
    assert queue.claim("w3", lease_s=60) is None
    assert queue.claim("w3", lease_s=60, kinds=()) is None


def test_heartbeat_extends_and_stale_leases_are_lost(
    queue: SqliteJobQueue, clock: FakeClock
) -> None:
    queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    claimed = queue.claim("w1", lease_s=60)
    assert claimed is not None
    clock.advance(30)
    lease = queue.heartbeat(claimed.job.id, claimed.lease.lease_id, lease_s=60)
    assert lease.expires_at == "2026-10-12T08:01:30.000Z"
    with pytest.raises(LeaseLost):
        queue.heartbeat(claimed.job.id, "other-lease", lease_s=60)
    with pytest.raises(NotFound):
        queue.heartbeat("missing", claimed.lease.lease_id, lease_s=60)
    clock.advance(61)
    with pytest.raises(LeaseLost):
        queue.heartbeat(claimed.job.id, claimed.lease.lease_id, lease_s=60)


def test_expired_lease_goes_back_to_the_queue_then_fails(
    queue: SqliteJobQueue, clock: FakeClock
) -> None:
    job = queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    for attempt in range(1, 4):
        claimed = queue.claim(f"w{attempt}", lease_s=30)
        assert claimed is not None
        assert claimed.job.attempts == attempt
        clock.advance(31)
        assert queue.expire_leases() == 1
        current = queue.get(job.id)
        assert current is not None
        assert current.error_code == "lease_expired"
        assert current.state == ("failed" if attempt == 3 else "queued")
    assert queue.claim("w9", lease_s=30) is None


def track_status(db: Database, track_id: str) -> str:
    with db.read() as conn:
        row = conn.execute("SELECT status FROM tracks WHERE id = ?", (track_id,)).fetchone()
    assert row is not None
    return str(row["status"])


def test_expired_lease_with_attempts_used_up_fails_the_track_too(
    queue: SqliteJobQueue, clock: FakeClock, db: Database
) -> None:
    queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    queue.enqueue(track_id="t2", video_id="Wq5Jd7HsKe2", priority=0)
    for _ in range(3):
        assert queue.claim("w", lease_s=30) is not None
        clock.advance(31)
    assert queue.claim("w", lease_s=30) is not None
    assert track_status(db, "t1") == "failed"
    assert track_status(db, "t2") == "pending"


def test_each_attempt_has_its_own_staging_dir(queue: SqliteJobQueue, clock: FakeClock) -> None:
    job = queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    first = queue.claim("w1", lease_s=30)
    assert first is not None
    assert first.job.staging_dir == f"{job.id}/1"
    clock.advance(31)
    second = queue.claim("w2", lease_s=30)
    assert second is not None
    assert second.job.staging_dir == f"{job.id}/2"


def test_release_ends_the_lease(queue: SqliteJobQueue, clock: FakeClock) -> None:
    job = queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    claimed = queue.claim("w1", lease_s=60)
    assert claimed is not None
    later = format_ts(clock.now())
    retried = queue.release(
        claimed.job.id,
        claimed.lease.lease_id,
        state="queued",
        error_code="network_error",
        error_message="timeout",
        not_before=later,
    )
    assert retried == JobResult(job.id, "queued", 1, later)
    current = queue.get(job.id)
    assert current is not None
    assert current.state == "queued"
    assert current.lease_id is None
    again = queue.claim("w1", lease_s=60)
    assert again is not None
    to_tagging(queue, again)
    done = queue.release(again.job.id, again.lease.lease_id, state="ready")
    assert done == JobResult(job.id, "ready", 2, None)


def test_repeating_a_release_with_the_same_lease_returns_the_same_result(
    queue: SqliteJobQueue, clock: FakeClock
) -> None:
    """A worker that lost the response retries: same result, nothing changes (contract)."""
    job = queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    claimed = queue.claim("w1", lease_s=60)
    assert claimed is not None
    later = format_ts(clock.now())
    first = queue.release(job.id, claimed.lease.lease_id, state="queued", not_before=later)
    # Another worker claims the retry before the first worker repeats its call.
    second_claim = queue.claim("w2", lease_s=60)
    assert second_claim is not None
    repeated = queue.release(job.id, claimed.lease.lease_id, state="queued", not_before=later)
    assert repeated == first
    with pytest.raises(InvalidStateTransition):
        queue.release(job.id, claimed.lease.lease_id, state="ready")
    current = queue.get(job.id)
    assert current is not None
    assert current.state == "downloading"
    assert current.lease_id == second_claim.lease.lease_id
    to_tagging(queue, second_claim)
    done = queue.release(job.id, second_claim.lease.lease_id, state="ready")
    assert queue.release(job.id, second_claim.lease.lease_id, state="ready") == done
    with pytest.raises(InvalidStateTransition):
        queue.release(job.id, second_claim.lease.lease_id, state="failed")
    with pytest.raises(LeaseLost):
        queue.release(job.id, "never-issued", state="ready")


def test_failed_and_cancelled_releases_fail_the_track(queue: SqliteJobQueue, db: Database) -> None:
    queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    claimed = queue.claim("w1", lease_s=60)
    assert claimed is not None
    result = queue.release(
        claimed.job.id, claimed.lease.lease_id, state="failed", error_code="video_unavailable"
    )
    assert result.state == "failed"
    assert track_status(db, "t1") == "failed"


def test_cancel_a_queued_job_at_once(queue: SqliteJobQueue, db: Database) -> None:
    job = queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    cancelled = queue.request_cancel(job.id)
    assert cancelled.state == "cancelled"
    assert cancelled.error_code == "cancelled"
    assert track_status(db, "t1") == "failed"
    assert queue.claim("w1", lease_s=60) is None
    assert queue.request_cancel(job.id) == cancelled


def test_cancel_a_leased_job_through_its_heartbeat(
    queue: SqliteJobQueue, clock: FakeClock, db: Database
) -> None:
    job = queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    claimed = queue.claim("w1", lease_s=60)
    assert claimed is not None
    assert not queue.heartbeat(job.id, claimed.lease.lease_id, lease_s=60).cancel_requested
    assert queue.request_cancel(job.id).cancel_requested == 1
    assert queue.heartbeat(job.id, claimed.lease.lease_id, lease_s=60).cancel_requested
    result = queue.release(job.id, claimed.lease.lease_id, state="cancelled")
    assert result.state == "cancelled"
    assert track_status(db, "t1") == "failed"
    with pytest.raises(NotFound):
        queue.request_cancel("missing")


def test_a_cancelled_job_whose_lease_expires_ends_cancelled(
    queue: SqliteJobQueue, clock: FakeClock, db: Database
) -> None:
    job = queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    assert queue.claim("w1", lease_s=30) is not None
    queue.request_cancel(job.id)
    clock.advance(31)
    assert queue.expire_leases() == 1
    current = queue.get(job.id)
    assert current is not None
    assert (current.state, current.error_code, current.cancel_requested) == (
        "cancelled",
        "cancelled",
        0,
    )
    assert track_status(db, "t1") == "failed"


def test_claim_skips_a_job_another_claimer_took_first(
    queue: SqliteJobQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The conditional update is what protects concurrent claims: zero rows means taken."""
    queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    real_take = SqliteJobQueue._take
    calls: list[str] = []

    def lose_the_first_race(
        self: SqliteJobQueue, conn: Connection, job_id: str, **fields: Any
    ) -> bool:
        calls.append(job_id)
        if len(calls) == 1:
            return False
        return real_take(self, conn, job_id, **fields)

    monkeypatch.setattr(SqliteJobQueue, "_take", lose_the_first_race)
    claimed = queue.claim("w1", lease_s=60)
    assert claimed is not None
    assert len(calls) == 2
    monkeypatch.setattr(SqliteJobQueue, "_take", lambda *_args, **_fields: False)
    queue.enqueue(track_id="t2", video_id="Wq5Jd7HsKe2", priority=1)
    assert queue.claim("w2", lease_s=60) is None


def test_take_refuses_a_job_that_is_not_queued(queue: SqliteJobQueue, db: Database) -> None:
    job = queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    assert queue.claim("w1", lease_s=60) is not None
    with db.transaction() as conn:
        now = "2026-10-12T08:00:00.000Z"
        assert not queue._take(conn, job.id, worker_id="w2", lease_id="l2", now=now, expires=now)


# ---------------------------------------------------------------- T08: progress, fail, retry


def claim(queue: SqliteJobQueue, worker: str = "w1", lease_s: int = 60) -> Claimed:
    claimed = queue.claim(worker, lease_s=lease_s)
    assert claimed is not None
    return claimed


def test_progress_stores_the_stream_state_and_extends_the_lease(
    queue: SqliteJobQueue, clock: FakeClock
) -> None:
    queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    claimed = claim(queue, lease_s=45)
    clock.advance(10)
    lease = queue.progress(claimed.job.id, claimed.lease.lease_id, report(claimed))
    assert lease.expires_at == "2026-10-12T08:00:55.000Z"
    assert lease.heartbeat_s == 15
    assert not lease.cancel_requested
    job = queue.get(claimed.job.id)
    assert job is not None
    assert (job.state, job.bytes_downloaded, job.expected_size, job.format_id) == (
        "downloading",
        100,
        200,
        "251",
    )
    assert (job.part_path, job.final_path, job.progressive, job.finished) == (
        f"{claimed.job.staging_dir}/Rb8Tn3ZcYv0.webm.part",
        f"{claimed.job.staging_dir}/Rb8Tn3ZcYv0.webm",
        True,
        False,
    )
    assert job.content_type == "audio/webm"
    assert job.progress == 0.5


def test_progress_never_goes_back(queue: SqliteJobQueue) -> None:
    queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    claimed = claim(queue)
    lease = claimed.lease.lease_id
    queue.progress(claimed.job.id, lease, report(claimed, bytes_downloaded=150, progress=0.75))
    queue.progress(claimed.job.id, lease, report(claimed, bytes_downloaded=200, finished=True))
    # A late, out-of-order report (retried after a timeout) does not move anything back.
    queue.progress(claimed.job.id, lease, report(claimed, bytes_downloaded=50, progress=0.25))
    job = queue.get(claimed.job.id)
    assert job is not None
    assert (job.bytes_downloaded, job.progress, job.finished) == (200, 0.75, True)
    to_tagging(queue, claimed)
    with pytest.raises(InvalidStateTransition):
        queue.progress(claimed.job.id, lease, report(claimed))


def test_progress_without_a_known_size_until_it_is_known(queue: SqliteJobQueue) -> None:
    queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    claimed = claim(queue)
    lease = claimed.lease.lease_id
    queue.progress(claimed.job.id, lease, report(claimed, expected_size=None))
    queue.progress(claimed.job.id, lease, report(claimed, expected_size=300))
    with pytest.raises(InvalidStateTransition, match="expectedSize"):
        queue.progress(claimed.job.id, lease, report(claimed, expected_size=301))
    with pytest.raises(InvalidStateTransition, match="formatId"):
        queue.progress(claimed.job.id, lease, report(claimed, expected_size=300, format_id="140"))


@pytest.mark.parametrize(
    "path",
    [
        "other-job/1/x.webm",
        "../x.webm",
        "/abs/x.webm",
        "{dir}",
        "{job}/2/x.webm",
        "{dir}/../2/x.webm",
    ],
)
def test_progress_paths_stay_in_the_attempt_directory(queue: SqliteJobQueue, path: str) -> None:
    queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    claimed = claim(queue)
    bad = path.format(dir=claimed.job.staging_dir, job=claimed.job.id)
    for field in ("part_path", "final_path"):
        with pytest.raises(PathRejected):
            queue.progress(claimed.job.id, claimed.lease.lease_id, report(claimed, **{field: bad}))


def test_progress_needs_the_current_lease(queue: SqliteJobQueue, clock: FakeClock) -> None:
    queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    claimed = claim(queue, lease_s=30)
    with pytest.raises(LeaseLost):
        queue.progress(claimed.job.id, "stale", report(claimed))
    clock.advance(31)
    with pytest.raises(LeaseLost):
        queue.progress(claimed.job.id, claimed.lease.lease_id, report(claimed))


def test_progress_tells_the_worker_about_a_cancel(queue: SqliteJobQueue) -> None:
    job = queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    claimed = claim(queue)
    queue.request_cancel(job.id)
    assert queue.progress(job.id, claimed.lease.lease_id, report(claimed)).cancel_requested


def test_a_claim_without_a_recorded_lease_length_extends_by_the_default(
    queue: SqliteJobQueue, db: Database
) -> None:
    queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    claimed = claim(queue, lease_s=20)
    with db.transaction() as conn:
        conn.execute("UPDATE jobs SET lease_seconds = NULL")
    lease = queue.progress(claimed.job.id, claimed.lease.lease_id, report(claimed))
    assert lease.expires_at == "2026-10-12T08:01:00.000Z"


def test_a_retryable_failure_goes_back_with_backoff(db: Database, clock: FakeClock) -> None:
    add_track(db, clock, "t1", "Rb8Tn3ZcYv0")
    queue = SqliteJobQueue(db, clock, rand=lambda: 0.5)
    job = queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    first = claim(queue)
    result = queue.fail(
        job.id, first.lease.lease_id, error_code="network_error", retryable=True, message="slow"
    )
    assert result == JobResult(job.id, "queued", 1, "2026-10-12T08:00:30.000Z")
    stored = queue.get(job.id)
    assert stored is not None
    assert (stored.error_code, stored.error_message) == ("network_error", "slow")
    assert queue.claim("w2", lease_s=60) is None
    clock.advance(30)
    second = claim(queue, "w2")
    assert second.job.attempts == 2
    result = queue.fail(
        job.id, second.lease.lease_id, error_code="internal_error", retryable=True, message="x"
    )
    assert result.not_before == "2026-10-12T08:02:30.000Z"
    clock.advance(120)
    third = claim(queue, "w3")
    result = queue.fail(
        job.id, third.lease.lease_id, error_code="network_error", retryable=True, message="x"
    )
    assert result == JobResult(job.id, "failed", 3, None)
    assert track_status(db, "t1") == "failed"
    repeated = queue.fail(
        job.id, third.lease.lease_id, error_code="network_error", retryable=True, message="x"
    )
    assert repeated == result
    with pytest.raises(InvalidStateTransition):
        queue.complete(job.id, third.lease.lease_id, lambda _conn, _job: None)


def test_a_non_retryable_failure_ends_the_job(queue: SqliteJobQueue, db: Database) -> None:
    job = queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    claimed = claim(queue)
    result = queue.fail(
        job.id,
        claimed.lease.lease_id,
        error_code="video_unavailable",
        retryable=True,
        message="gone",
    )
    assert (result.state, result.not_before) == ("failed", None)
    assert track_status(db, "t1") == "failed"


def test_a_failure_after_an_admin_cancel_ends_cancelled(
    queue: SqliteJobQueue, db: Database
) -> None:
    job = queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    claimed = claim(queue)
    queue.request_cancel(job.id)
    result = queue.fail(
        job.id, claimed.lease.lease_id, error_code="network_error", retryable=True, message="x"
    )
    assert result.state == "cancelled"
    stored = queue.get(job.id)
    assert stored is not None
    assert (stored.state, stored.error_code, stored.cancel_requested) == (
        "cancelled",
        "cancelled",
        0,
    )
    assert track_status(db, "t1") == "failed"


def test_fail_needs_the_current_lease(queue: SqliteJobQueue) -> None:
    job = queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    claim(queue)
    with pytest.raises(LeaseLost):
        queue.fail(job.id, "stale", error_code="network_error", retryable=True, message="x")
    with pytest.raises(NotFound):
        queue.fail("missing", "stale", error_code="network_error", retryable=True, message="x")


def test_complete_runs_the_finalizer_in_the_release(queue: SqliteJobQueue) -> None:
    job = queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    claimed = claim(queue)
    seen: list[str] = []

    def finalize(_conn: Connection, current: Job) -> None:
        seen.append(current.state)

    with pytest.raises(InvalidStateTransition):
        queue.complete(job.id, claimed.lease.lease_id, finalize)
    assert seen == []
    to_tagging(queue, claimed)
    result = queue.complete(job.id, claimed.lease.lease_id, finalize)
    assert result == JobResult(job.id, "ready", 1, None)
    assert seen == ["tagging"]
    assert queue.complete(job.id, claimed.lease.lease_id, finalize) == result
    assert seen == ["tagging"]
    done = queue.get(job.id)
    assert done is not None
    assert (done.state, done.progress, done.lease_id) == ("ready", 1.0, None)
    # A ready job is final: a new request returns it as it is.
    assert queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=100) == done


def test_a_failing_finalizer_rolls_the_release_back(queue: SqliteJobQueue) -> None:
    job = queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    claimed = claim(queue)
    to_tagging(queue, claimed)

    def refuse(_conn: Connection, _job: Job) -> None:
        raise NotFound("no file")

    with pytest.raises(NotFound):
        queue.complete(job.id, claimed.lease.lease_id, refuse)
    current = queue.get(job.id)
    assert current is not None
    assert (current.state, current.lease_id) == ("tagging", claimed.lease.lease_id)


def test_a_new_request_requeues_a_failed_job_with_attempts_reset(
    queue: SqliteJobQueue, db: Database
) -> None:
    job = queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    claimed = claim(queue)
    queue.fail(
        job.id,
        claimed.lease.lease_id,
        error_code="video_unavailable",
        retryable=False,
        message="gone",
    )
    assert track_status(db, "t1") == "failed"
    again = queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=PRIORITY_KEEP)
    assert again.id == job.id
    assert (again.state, again.attempts, again.priority, again.error_code) == (
        "queued",
        0,
        PRIORITY_KEEP,
        None,
    )
    assert track_status(db, "t1") == "pending"
    cancelled = queue.request_cancel(job.id)
    assert cancelled.state == "cancelled"
    assert queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1).state == "queued"


def test_a_new_attempt_keeps_the_previous_format_and_size(
    queue: SqliteJobQueue, clock: FakeClock
) -> None:
    job = queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    first = claim(queue, lease_s=30)
    assert (first.job.previous_format_id, first.job.previous_expected_size) == (None, None)
    queue.progress(job.id, first.lease.lease_id, report(first, expected_size=4096))
    clock.advance(31)
    second = claim(queue, lease_s=30)
    assert (second.job.previous_format_id, second.job.previous_expected_size) == ("251", 4096)
    assert (second.job.format_id, second.job.expected_size, second.job.part_path) == (
        None,
        None,
        None,
    )
    # The second attempt dies before its first report: the comparison base survives.
    clock.advance(31)
    third = claim(queue, lease_s=30)
    assert (third.job.previous_format_id, third.job.previous_expected_size) == ("251", 4096)
    queue.progress(job.id, third.lease.lease_id, report(third, format_id="140", expected_size=None))
    queue.fail(
        job.id, third.lease.lease_id, error_code="internal_error", retryable=False, message="x"
    )
    queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    fourth = claim(queue)
    assert (fourth.job.previous_format_id, fourth.job.previous_expected_size) == ("140", None)


def test_jobs_are_found_by_video_and_carry_hints(queue: SqliteJobQueue, db: Database) -> None:
    job = queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    found = queue.by_video("Rb8Tn3ZcYv0")
    assert found is not None
    assert found.id == job.id
    assert queue.by_video("Zz0000000zz") is None
    hints = queue.hints(job)
    assert (hints.title, hints.artist_name, hints.album_name) == (
        "Glass Orchard",
        "The Paper Lanterns",
        None,
    )
    with db.transaction() as conn:
        conn.execute("DELETE FROM tracks WHERE id = 't1'")
    with pytest.raises(NotFound):
        queue.hints(job)


def test_staging_dirs_never_repeat_across_re_requests(queue: SqliteJobQueue) -> None:
    job = queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    first = claim(queue)
    assert (first.job.attempts, first.job.staging_dir) == (1, f"{job.id}/1")
    queue.fail(
        job.id, first.lease.lease_id, error_code="video_unavailable", retryable=False, message="x"
    )
    queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    again = claim(queue)
    # The retry budget starts over, the staging sequence does not.
    assert (again.job.attempts, again.job.attempt_seq) == (1, 2)
    assert again.job.staging_dir == f"{job.id}/2"


def test_paths_are_fixed_by_the_first_report(queue: SqliteJobQueue) -> None:
    queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    claimed = claim(queue)
    lease, base = claimed.lease.lease_id, claimed.job.staging_dir
    queue.progress(claimed.job.id, lease, report(claimed))
    with pytest.raises(InvalidStateTransition, match="partPath"):
        queue.progress(claimed.job.id, lease, report(claimed, part_path=f"{base}/other.part"))
    with pytest.raises(InvalidStateTransition, match="finalPath"):
        queue.progress(claimed.job.id, lease, report(claimed, final_path=f"{base}/other.webm"))


def test_a_write_that_matches_no_row_is_a_lost_lease(queue: SqliteJobQueue, db: Database) -> None:
    """Under READ COMMITTED another claimer can win between the read and the conditional
    update; a trigger that skips the update stands in for that race here."""
    job = queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
    claimed = claim(queue)
    with db.transaction() as conn:
        conn.execute(
            "CREATE TRIGGER steal BEFORE UPDATE ON jobs WHEN NEW.lease_id = OLD.lease_id"
            " OR NEW.lease_id IS NULL BEGIN SELECT RAISE(IGNORE); END"
        )
    with pytest.raises(LeaseLost):
        queue.progress(job.id, claimed.lease.lease_id, report(claimed))
    seen: list[str] = []

    def finalize(conn: Connection, current: Job) -> None:
        conn.execute("UPDATE tracks SET status = 'ready' WHERE id = ?", (current.track_id,))
        seen.append(current.id)

    with pytest.raises(LeaseLost):
        queue.release(job.id, claimed.lease.lease_id, state="failed", finalize=finalize)
    assert seen == [job.id]
    assert track_status(db, "t1") == "pending"
