# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`complete`: an archived file makes the track ready; a merge moves every reference."""

from pathlib import Path
from typing import cast

import pytest

from tests.jobs.test_queue import add_track, to_tagging
from ultimatetunes.core.clock import FakeClock, format_ts
from ultimatetunes.core.storage import LocalLibraryStore
from ultimatetunes.db import Database
from ultimatetunes.db.driver import Connection, Result
from ultimatetunes.errors import Conflict, InvalidStateTransition, PathRejected
from ultimatetunes.jobs import archive
from ultimatetunes.jobs.archive import archive_finalizer
from ultimatetunes.jobs.queue import Claimed, SqliteJobQueue

VIDEO = "Rb8Tn3ZcYv0"
PATH = "The Paper Lanterns/Lanterns at Dusk/04 - Glass Orchard.opus"


@pytest.fixture
def library(tmp_path: Path) -> LocalLibraryStore:
    root = tmp_path / "music"
    root.mkdir(exist_ok=True)
    return LocalLibraryStore(root)


@pytest.fixture
def queue(db: Database, clock: FakeClock) -> SqliteJobQueue:
    add_track(db, clock, "pending", VIDEO)
    return SqliteJobQueue(db, clock)


def run(db: Database, sql: str, params: tuple[object, ...] = ()) -> None:
    with db.transaction() as conn:
        conn.execute(sql, params)


def rows(db: Database, sql: str, params: tuple[object, ...] = ()) -> list[dict[str, object]]:
    with db.read() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def claimed_in_tagging(queue: SqliteJobQueue) -> Claimed:
    queue.enqueue(track_id="pending", video_id=VIDEO, priority=1)
    claimed = queue.claim("w1", lease_s=60)
    assert claimed is not None
    to_tagging(queue, claimed)
    return claimed


def register(db: Database, claimed: Claimed, *, size: int = 4) -> None:
    """What `registerTrack` (library area) leaves behind for an archived file."""
    run(db, "UPDATE tracks SET size_bytes = ? WHERE id = 'pending'", (size,))
    run(db, "UPDATE jobs SET library_path = ? WHERE id = ?", (PATH, claimed.job.id))


def now(clock: FakeClock) -> str:
    return format_ts(clock.now())


def test_complete_makes_the_archived_track_ready(
    queue: SqliteJobQueue, db: Database, clock: FakeClock, library: LocalLibraryStore
) -> None:
    claimed = claimed_in_tagging(queue)
    finalize = archive_finalizer(library, track_id="pending", library_path=PATH, now=now(clock))
    with pytest.raises(InvalidStateTransition, match="registered"):
        queue.complete(claimed.job.id, claimed.lease.lease_id, finalize)
    register(db, claimed)
    with pytest.raises(Conflict, match="missing"):
        queue.complete(claimed.job.id, claimed.lease.lease_id, finalize)
    with library.open_write(PATH) as out:
        out.write(b"abc")
    with pytest.raises(Conflict, match="size"):
        queue.complete(claimed.job.id, claimed.lease.lease_id, finalize)
    with library.open_write(PATH) as out:
        out.write(b"abcd")
    other_path = archive_finalizer(library, track_id="pending", library_path="x.opus", now="n")
    with pytest.raises(Conflict, match="registration"):
        queue.complete(claimed.job.id, claimed.lease.lease_id, other_path)
    other_track = archive_finalizer(library, track_id="other", library_path=PATH, now="n")
    with pytest.raises(Conflict, match="registration"):
        queue.complete(claimed.job.id, claimed.lease.lease_id, other_track)
    bad = archive_finalizer(library, track_id="pending", library_path="../x.opus", now="n")
    with pytest.raises(PathRejected):
        queue.complete(claimed.job.id, claimed.lease.lease_id, bad)
    result = queue.complete(claimed.job.id, claimed.lease.lease_id, finalize)
    assert result.state == "ready"
    track = rows(db, "SELECT status, path, archived_at FROM tracks WHERE id = 'pending'")[0]
    assert track == {"status": "ready", "path": PATH, "archived_at": "2026-10-12T08:00:00.000Z"}
    job = queue.get(claimed.job.id)
    assert job is not None
    assert job.library_path == PATH


def seed_references(db: Database, clock: FakeClock) -> None:
    """Two users; the existing track `kept` and the pending one share fans and plays."""
    stamp = now(clock)
    for user in ("ana", "ben"):
        run(
            db,
            "INSERT INTO users (id, username, password_hash, role, created_at, updated_at)"
            " VALUES (?, ?, 'x', 'user', ?, ?)",
            (user, user, stamp, stamp),
        )
    add_track(db, clock, "kept", "Kp9Lm2Zx0aB")
    run(db, "UPDATE tracks SET status = 'ready' WHERE id = 'kept'")
    run(db, "INSERT INTO track_aliases VALUES (?, 'pending', ?)", (f"yt:{VIDEO}", stamp))
    # Ana starred both, Ben only the pending one.
    for user, track in (("ana", "kept"), ("ana", "pending"), ("ben", "pending")):
        run(db, "INSERT INTO starred_tracks VALUES (?, ?, ?)", (user, track, stamp))
    run(
        db,
        "INSERT INTO playlists (id, owner_id, name, created_at, updated_at)"
        " VALUES ('pl', 'ana', 'Mix', ?, ?)",
        (stamp, stamp),
    )
    run(db, "INSERT INTO playlist_tracks VALUES ('pl', 0, 'pending', ?)", (stamp,))
    run(db, "INSERT INTO playlist_tracks VALUES ('pl', 1, 'kept', ?)", (stamp,))
    run(
        db,
        "INSERT INTO play_history (id, user_id, track_id, played_at) VALUES"
        " ('h1', 'ana', 'pending', ?)",
        (stamp,),
    )
    run(db, "INSERT INTO user_track_stats VALUES ('ana', 'kept', 2, '2026-10-01T00:00:00.000Z')")
    run(
        db,
        "INSERT INTO user_track_stats VALUES ('ana', 'pending', 3, '2026-10-11T00:00:00.000Z')",
    )
    run(db, "INSERT INTO user_track_stats VALUES ('ben', 'pending', 1, NULL)")
    run(
        db,
        "INSERT INTO imports (id, user_id, source, state, created_at, updated_at)"
        " VALUES ('im', 'ana', 'csv', 'done', ?, ?)",
        (stamp, stamp),
    )
    run(
        db,
        "INSERT INTO import_items (import_id, position, source_title, state, track_id)"
        " VALUES ('im', 0, 'Glass Orchard', 'matched', 'pending')",
    )


def test_complete_applies_a_merge_in_one_transaction(
    queue: SqliteJobQueue, db: Database, clock: FakeClock, library: LocalLibraryStore
) -> None:
    seed_references(db, clock)
    claimed = claimed_in_tagging(queue)
    merged = archive_finalizer(library, track_id="kept", library_path=None, now=now(clock))
    with pytest.raises(InvalidStateTransition, match="merge decision"):
        queue.complete(claimed.job.id, claimed.lease.lease_id, merged)
    run(db, "UPDATE jobs SET merge_into_track_id = 'kept' WHERE id = ?", (claimed.job.id,))
    wrong = archive_finalizer(library, track_id="pending", library_path=None, now="n")
    with pytest.raises(Conflict, match="merge decision"):
        queue.complete(claimed.job.id, claimed.lease.lease_id, wrong)
    result = queue.complete(claimed.job.id, claimed.lease.lease_id, merged)
    assert result.state == "ready"
    assert rows(db, "SELECT track_id FROM track_aliases") == [{"track_id": "kept"}]
    assert rows(db, "SELECT user_id, track_id FROM starred_tracks ORDER BY user_id") == [
        {"user_id": "ana", "track_id": "kept"},
        {"user_id": "ben", "track_id": "kept"},
    ]
    assert rows(db, "SELECT track_id FROM playlist_tracks ORDER BY position") == [
        {"track_id": "kept"},
        {"track_id": "kept"},
    ]
    assert rows(db, "SELECT track_id FROM play_history") == [{"track_id": "kept"}]
    assert rows(db, "SELECT track_id FROM import_items") == [{"track_id": "kept"}]
    assert rows(
        db,
        "SELECT user_id, track_id, play_count, last_played_at FROM user_track_stats"
        " ORDER BY user_id",
    ) == [
        {
            "user_id": "ana",
            "track_id": "kept",
            "play_count": 5,
            "last_played_at": "2026-10-11T00:00:00.000Z",
        },
        {"user_id": "ben", "track_id": "kept", "play_count": 1, "last_played_at": None},
    ]
    pending = rows(db, "SELECT status, merged_into FROM tracks WHERE id = 'pending'")
    assert pending == [{"status": "merged", "merged_into": "kept"}]
    # Repeating complete returns the stored result and changes nothing.
    assert queue.complete(claimed.job.id, claimed.lease.lease_id, merged) == result


def test_a_merge_never_points_at_a_merged_track(
    queue: SqliteJobQueue, db: Database, clock: FakeClock, library: LocalLibraryStore
) -> None:
    add_track(db, clock, "final", "Fn1Lm2Zx0aB")
    add_track(db, clock, "old", "Od1Lm2Zx0aB")
    run(db, "UPDATE tracks SET status = 'ready' WHERE id = 'final'")
    run(db, "UPDATE tracks SET status = 'merged', merged_into = 'final' WHERE id = 'old'")
    claimed = claimed_in_tagging(queue)
    run(db, "UPDATE jobs SET merge_into_track_id = 'old' WHERE id = ?", (claimed.job.id,))
    finalize = archive_finalizer(library, track_id="final", library_path=None, now=now(clock))
    queue.complete(claimed.job.id, claimed.lease.lease_id, finalize)
    assert rows(db, "SELECT merged_into FROM tracks WHERE id = 'pending'") == [
        {"merged_into": "final"}
    ]


def test_a_merge_target_that_vanished_is_a_conflict() -> None:
    """Foreign keys make this impossible in the database; the check stays as a guard."""

    class Empty:
        dialect = "sqlite"

        def execute(self, sql: str, params: object = ()) -> Result:
            return Result([], 0)

    with pytest.raises(Conflict, match="gone"):
        archive._target(cast("Connection", Empty()), "gone")
