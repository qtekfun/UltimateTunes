# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""JobQueue on SQLite: deduplication, leases, heartbeats and lease expiry."""

import pytest

from ultimatetunes.core.clock import FakeClock, format_ts
from ultimatetunes.db import Database
from ultimatetunes.errors import LeaseLost, NotFound
from ultimatetunes.jobs.queue import PRIORITY_KEEP, PRIORITY_STREAM, SqliteJobQueue


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


def test_release_ends_the_lease(queue: SqliteJobQueue, clock: FakeClock) -> None:
    queue.enqueue(track_id="t1", video_id="Rb8Tn3ZcYv0", priority=1)
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
    assert retried.state == "queued"
    assert retried.lease_id is None
    with pytest.raises(LeaseLost):
        queue.release(claimed.job.id, claimed.lease.lease_id, state="ready")
    again = queue.claim("w1", lease_s=60)
    assert again is not None
    done = queue.release(again.job.id, again.lease.lease_id, state="ready")
    assert done.state == "ready"
