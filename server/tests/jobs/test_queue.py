# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""JobQueue on SQLite: deduplication, leases, heartbeats and lease expiry."""

import pytest

from ultimatetunes.core.clock import FakeClock, format_ts
from ultimatetunes.db import Database
from ultimatetunes.db.driver import Connection
from ultimatetunes.errors import InvalidStateTransition, LeaseLost, NotFound
from ultimatetunes.jobs.queue import PRIORITY_KEEP, PRIORITY_STREAM, JobResult, SqliteJobQueue


def add_track(db: Database, clock: FakeClock, track_id: str, video_id: str) -> None:
    now = format_ts(clock.now())
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO tracks (id, status, title, title_norm, artist_name, yt_video_id,"
            " created_at, updated_at) VALUES (?, 'pending', 'Glass Orchard', 'glass orchard',"
            " 'The Paper Lanterns', ?, ?, ?)",
            (track_id, video_id, now, now),
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
        self: SqliteJobQueue, conn: Connection, job_id: str, **fields: str
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
