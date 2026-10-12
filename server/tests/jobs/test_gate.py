# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""DownloadGate through SqliteJobQueue: duration, disk space and per-user limits."""

import pytest

from ultimatetunes.core.clock import FakeClock, format_ts
from ultimatetunes.core.limits import DownloadLimits
from ultimatetunes.db import Database
from ultimatetunes.errors import InvalidParameter, RateLimited
from ultimatetunes.jobs.gate import RETRY_BYTES_S, RETRY_QUEUED_S, RETRY_SPACE_S, DownloadGate
from ultimatetunes.jobs.queue import PRIORITY_KEEP, SqliteJobQueue

GIB = 1024**3
ALICE = "0199d6a2-0000-7000-8000-00000000a11c"
BOB = "0199d6a2-0000-7000-8000-000000000b0b"


class Disk:
    """A store that only answers how much space is free."""

    def __init__(self, free: int) -> None:
        self.free = free
        self.broken = False

    def free_bytes(self) -> int:
        if self.broken:
            raise OSError("gone")
        return self.free


def add_user(db: Database, clock: FakeClock, user_id: str, name: str) -> None:
    now = format_ts(clock.now())
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO users (id, username, password_hash, role, created_at, updated_at)"
            " VALUES (?, ?, 'x', 'user', ?, ?)",
            (user_id, name, now, now),
        )


def add_track(
    db: Database, clock: FakeClock, n: int, duration_ms: int | None = 200_000
) -> tuple[str, str]:
    track_id, video_id = f"t{n}", f"Video{n:06d}"
    now = format_ts(clock.now())
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO tracks (id, status, title, title_norm, artist_name, duration_ms,"
            " yt_video_id, created_at, updated_at) VALUES (?, 'pending', 'Glass Orchard',"
            " 'glass orchard', 'The Paper Lanterns', ?, ?, ?, ?)",
            (track_id, duration_ms, video_id, now, now),
        )
    return track_id, video_id


def limits() -> DownloadLimits:
    # Below the validated minimums, so built without validation.
    return DownloadLimits.model_construct(
        max_track_duration_s=1800,
        max_download_bytes=200 * 1024 * 1024,
        max_queued_jobs_per_user=3,
        max_download_bytes_per_day_per_user=10_000,
        min_free_bytes=2 * GIB,
    )


@pytest.fixture
def music() -> Disk:
    return Disk(10 * GIB)


@pytest.fixture
def staging() -> Disk:
    return Disk(10 * GIB)


@pytest.fixture
def queue(db: Database, clock: FakeClock, music: Disk, staging: Disk) -> SqliteJobQueue:
    add_user(db, clock, ALICE, "alice")
    add_user(db, clock, BOB, "bob")
    gate = DownloadGate(limits(), clock, (music, staging))  # type: ignore[arg-type]
    return SqliteJobQueue(db, clock, gate=gate)


def keep(queue: SqliteJobQueue, track: tuple[str, str], user: str | None = ALICE) -> str:
    track_id, video_id = track
    job = queue.enqueue(
        track_id=track_id, video_id=video_id, priority=PRIORITY_KEEP, requested_by=user
    )
    return job.id


def job_count(db: Database) -> int:
    with db.read() as conn:
        return int(str(conn.execute("SELECT COUNT(*) FROM jobs").scalar()))


def test_a_song_over_the_duration_limit_is_never_queued(
    db: Database, clock: FakeClock, queue: SqliteJobQueue
) -> None:
    too_long = add_track(db, clock, 1, duration_ms=1_800_001)
    with pytest.raises(InvalidParameter, match="1800 seconds"):
        keep(queue, too_long)
    assert job_count(db) == 0
    # Exactly the limit, and an unknown duration (left to yt-dlp's filter), pass.
    keep(queue, add_track(db, clock, 2, duration_ms=1_800_000))
    keep(queue, add_track(db, clock, 3, duration_ms=None))
    assert job_count(db) == 2


def test_a_refusal_rolls_back_the_whole_transaction(
    db: Database, clock: FakeClock, queue: SqliteJobQueue
) -> None:
    track_id, video_id = add_track(db, clock, 1, duration_ms=4_000_000)

    def request() -> None:
        with db.transaction() as conn:
            conn.execute("UPDATE tracks SET title = 'changed' WHERE id = ?", (track_id,))
            queue.enqueue_in(conn, track_id=track_id, video_id=video_id, priority=1)

    with pytest.raises(InvalidParameter):
        request()
    with db.read() as conn:
        title = conn.execute("SELECT title FROM tracks WHERE id = ?", (track_id,)).scalar()
    assert title == "Glass Orchard"


@pytest.fixture(params=["music", "staging"])
def low(request: pytest.FixtureRequest, music: Disk, staging: Disk) -> Disk:
    return music if request.param == "music" else staging


def test_low_disk_space_refuses_new_downloads_and_claims(
    db: Database, clock: FakeClock, queue: SqliteJobQueue, low: Disk
) -> None:
    keep(queue, add_track(db, clock, 1))
    disk = low
    disk.free = 2 * GIB - 1
    with pytest.raises(RateLimited) as refused:
        keep(queue, add_track(db, clock, 2))
    assert refused.value.retry_after_s == RETRY_SPACE_S
    assert queue.claim("w1", lease_s=60) is None
    disk.free = 2 * GIB
    claimed = queue.claim("w1", lease_s=60)
    assert claimed is not None


def test_a_store_that_cannot_say_counts_as_full(
    db: Database, clock: FakeClock, queue: SqliteJobQueue, staging: Disk
) -> None:
    staging.broken = True
    with pytest.raises(RateLimited):
        keep(queue, add_track(db, clock, 1))


def test_queued_and_running_jobs_per_user_are_capped(
    db: Database, clock: FakeClock, queue: SqliteJobQueue
) -> None:
    tracks = [add_track(db, clock, n) for n in range(6)]
    for track in tracks[:3]:
        keep(queue, track)
        clock.advance(1)  # the oldest job (Alice's first) is claimed first
    with pytest.raises(RateLimited) as refused:
        keep(queue, tracks[3])
    assert refused.value.retry_after_s == RETRY_QUEUED_S
    # Another user has a queue of its own; requests without a user are not counted.
    keep(queue, tracks[3], user=BOB)
    keep(queue, tracks[4], user=None)
    # Asking again for a job that is already queued starts nothing and is not refused.
    keep(queue, tracks[0])
    # A running job still counts; a finished one frees its place.
    claimed = queue.claim("w1", lease_s=60)
    assert claimed is not None
    with pytest.raises(RateLimited):
        keep(queue, tracks[5])
    queue.fail(
        claimed.job.id,
        claimed.lease.lease_id,
        error_code="video_unavailable",
        retryable=False,
        message="gone",
    )
    keep(queue, tracks[5])


def test_daily_download_bytes_per_user_are_capped(
    db: Database, clock: FakeClock, queue: SqliteJobQueue
) -> None:
    first = keep(queue, add_track(db, clock, 1))
    with db.transaction() as conn:
        conn.execute(
            "UPDATE jobs SET state = 'ready', bytes_downloaded = 10000, updated_at = ?"
            " WHERE id = ?",
            (format_ts(clock.now()), first),
        )
    second = add_track(db, clock, 2)
    with pytest.raises(RateLimited) as refused:
        keep(queue, second)
    assert refused.value.retry_after_s == RETRY_BYTES_S
    keep(queue, second, user=BOB)
    # The window is the last 24 hours.
    clock.advance(24 * 3600 + 1)
    keep(queue, add_track(db, clock, 3))


def test_a_requeue_is_checked_and_charged_to_the_new_requester(
    db: Database, clock: FakeClock, queue: SqliteJobQueue
) -> None:
    track = add_track(db, clock, 1)
    job_id = keep(queue, track)
    claimed = queue.claim("w1", lease_s=60)
    assert claimed is not None
    queue.fail(
        job_id, claimed.lease.lease_id, error_code="video_unavailable", retryable=False, message="x"
    )
    with db.transaction() as conn:
        conn.execute("UPDATE tracks SET duration_ms = 9000000 WHERE id = ?", (track[0],))
    with pytest.raises(InvalidParameter):
        keep(queue, track, user=BOB)
    with db.transaction() as conn:
        conn.execute("UPDATE tracks SET duration_ms = 1000 WHERE id = ?", (track[0],))
    keep(queue, track, user=BOB)
    job = queue.get(job_id)
    assert job is not None
    assert job.state == "queued"
    with db.read() as conn:
        owner = conn.execute("SELECT requested_by FROM jobs WHERE id = ?", (job_id,)).scalar()
    assert owner == BOB


def test_without_a_gate_nothing_is_checked(db: Database, clock: FakeClock) -> None:
    plain = SqliteJobQueue(db, clock)
    track_id, video_id = add_track(db, clock, 1, duration_ms=99_000_000)
    plain.enqueue(track_id=track_id, video_id=video_id, priority=1)
    assert plain.claim("w1", lease_s=60) is not None


def test_the_defaults() -> None:
    defaults = DownloadLimits()
    assert defaults.max_track_duration_s == 1800
    assert defaults.max_download_bytes == 200 * 1024 * 1024
    assert defaults.max_queued_jobs_per_user == 200
    assert defaults.max_download_bytes_per_day_per_user == 5 * GIB
    assert defaults.min_free_bytes == 2 * GIB
    assert defaults.too_long(1800.5)
    assert not defaults.too_long(None)


def test_the_limits_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UT_MAX_TRACK_DURATION_S", "600")
    monkeypatch.setenv("UT_MIN_FREE_BYTES", "0")
    loaded = DownloadLimits()
    assert (loaded.max_track_duration_s, loaded.min_free_bytes) == (600, 0)
