# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Library size limit: which tracks are freed, in which order, and what a freed track keeps."""

import json
import logging
from pathlib import Path

import anyio
import pytest

from ultimatetunes.core.clock import FakeClock, format_ts
from ultimatetunes.core.storage import LocalLibraryStore
from ultimatetunes.db import Database
from ultimatetunes.jobs.queue import PRIORITY_STREAM, SqliteJobQueue
from ultimatetunes.library import evict
from ultimatetunes.library.evict import Evictor, Policy

DAY = 24 * 3600.0
MB = 1_000_000


@pytest.fixture
def library(tmp_path: Path) -> LocalLibraryStore:
    root = tmp_path / "music"
    root.mkdir(exist_ok=True)
    return LocalLibraryStore(root)


@pytest.fixture
def evictor(db: Database, clock: FakeClock, library: LocalLibraryStore) -> Evictor:
    with db.transaction() as conn:
        now = format_ts(clock.now())
        for user in ("u1", "u2"):
            conn.execute(
                "INSERT INTO users (id, username, password_hash, role, created_at, updated_at)"
                " VALUES (?, ?, 'x', 'user', ?, ?)",
                (user, user, now, now),
            )
        conn.execute(
            "INSERT INTO artists (id, name, name_norm, created_at, updated_at)"
            " VALUES ('ar1', 'The Paper Lanterns', 'the paper lanterns', ?, ?)",
            (now, now),
        )
        conn.execute(
            "INSERT INTO albums (id, artist_id, name, name_norm, created_at, updated_at)"
            " VALUES ('al1', 'ar1', 'Glass Orchard', 'glass orchard', ?, ?)",
            (now, now),
        )
    return Evictor(db, library, clock)


def _video(n: int) -> str:
    return f"vid{n:08d}"


def _track(  # noqa: PLR0913 - the columns of one track row
    db: Database,
    clock: FakeClock,
    library: LocalLibraryStore,
    n: int,
    *,
    size: int = MB,
    video: bool = True,
    album: str | None = None,
    artist: str | None = None,
) -> str:
    track_id, path = f"t{n}", f"Artist/Album/{n:02d}.opus"
    target = library.root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"x" * 16)
    now = format_ts(clock.now())
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO tracks (id, status, title, title_norm, artist_id, album_id, artist_name,"
            " yt_video_id, path, size_bytes, format, content_type, archived_at, created_at,"
            " updated_at) VALUES (?, 'ready', ?, ?, ?, ?, 'The Paper Lanterns', ?, ?, ?, 'opus',"
            " 'audio/ogg', ?, ?, ?)",
            (
                track_id,
                f"Song {n}",
                f"song {n}",
                artist,
                album,
                _video(n) if video else None,
                path,
                size,
                now,
                now,
                now,
            ),
        )
    return track_id


def _play(db: Database, clock: FakeClock, user: str, track_id: str, count: int) -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO user_track_stats (user_id, track_id, play_count, last_played_at)"
            " VALUES (?, ?, ?, ?)",
            (user, track_id, count, format_ts(clock.now())),
        )


def _limit(db: Database, clock: FakeClock, max_bytes: int | None, grace_days: int = 30) -> None:
    with db.transaction() as conn:
        evict.save_policy(conn, Policy(max_bytes, grace_days), format_ts(clock.now()))


def _status(db: Database, track_id: str) -> tuple[str, str | None]:
    with db.read() as conn:
        row = conn.execute("SELECT status, path FROM tracks WHERE id = ?", (track_id,)).fetchone()
    assert row is not None
    return str(row["status"]), None if row["path"] is None else str(row["path"])


def _freed(db: Database) -> set[str]:
    with db.read() as conn:
        rows = conn.execute("SELECT id FROM tracks WHERE status = 'pending'").fetchall()
    return {str(r["id"]) for r in rows}


def _old(clock: FakeClock) -> None:
    """Moves past the default grace period, so the tracks added so far may be freed."""
    clock.advance(31 * DAY)


# ---------------------------------------------------------------------- policy


def test_no_limit_frees_nothing(
    db: Database, clock: FakeClock, library: LocalLibraryStore, evictor: Evictor
) -> None:
    for n in range(3):
        _track(db, clock, library, n)
    _old(clock)
    assert evictor.run_once() == evict.RunResult(0, 0, reached=True)
    plan = evictor.plan()
    assert (plan.over, plan.total_bytes, plan.target_bytes) == (False, 3 * MB, None)
    assert _freed(db) == set()


def test_policy_round_trip_and_unreadable_values(db: Database, clock: FakeClock) -> None:
    with db.read() as conn:
        assert evict.read_policy(conn) == Policy(None, evict.DEFAULT_GRACE_DAYS)
    _limit(db, clock, 5 * MB, grace_days=7)
    with db.read() as conn:
        assert evict.read_policy(conn) == Policy(5 * MB, 7)
    _limit(db, clock, None, grace_days=7)
    with db.read() as conn:
        assert evict.read_policy(conn) == Policy(None, 7)
    now = format_ts(clock.now())
    for raw_max, raw_grace, expected in (
        ("lots", "soon", Policy(None, evict.DEFAULT_GRACE_DAYS)),
        ("-5", "-3", Policy(None, 0)),
        ("0", "99999", Policy(None, evict.MAX_GRACE_DAYS)),
    ):
        with db.transaction() as conn:
            evict._put(conn, evict.KEY_MAX_BYTES, raw_max, now)
            evict._put(conn, evict.KEY_GRACE_DAYS, raw_grace, now)
        with db.read() as conn:
            assert evict.read_policy(conn) == expected


def test_last_run_ignores_garbage(db: Database, clock: FakeClock) -> None:
    with db.read() as conn:
        assert evict.last_run(conn) is None
    now = format_ts(clock.now())
    for raw in ("not json", "[1, 2]"):
        with db.transaction() as conn:
            evict._put(conn, evict.KEY_LAST_RUN, raw, now)
        with db.read() as conn:
            assert evict.last_run(conn) is None


# ---------------------------------------------------------------------- order


def test_under_the_limit_previews_the_order(
    db: Database, clock: FakeClock, library: LocalLibraryStore, evictor: Evictor
) -> None:
    for n in range(4):
        _track(db, clock, library, n)
    _play(db, clock, "u1", "t0", 5)
    clock.advance(DAY)
    _play(db, clock, "u1", "t1", 1)
    clock.advance(DAY)
    _play(db, clock, "u2", "t2", 1)
    _old(clock)
    _limit(db, clock, 10 * MB)
    plan = evictor.plan(preview=3)
    # Never played first, then one play (the one played longer ago first), then five plays.
    assert [c.track_id for c in plan.candidates] == ["t3", "t1", "t2"]
    assert plan.candidates[0].last_played is None
    assert plan.candidates[1].plays == 1
    assert plan.over is False
    assert plan.reachable is True
    assert evictor.run_once() == evict.RunResult(0, 0, reached=True)


def test_plays_of_every_user_add_up(
    db: Database, clock: FakeClock, library: LocalLibraryStore, evictor: Evictor
) -> None:
    for n in range(2):
        _track(db, clock, library, n)
    _play(db, clock, "u1", "t0", 2)
    _play(db, clock, "u2", "t0", 2)
    _play(db, clock, "u1", "t1", 3)
    _old(clock)
    _limit(db, clock, 10 * MB)
    assert [(c.track_id, c.plays) for c in evictor.plan().candidates] == [("t1", 3), ("t0", 4)]


def test_equal_tracks_go_oldest_archived_first(
    db: Database, clock: FakeClock, library: LocalLibraryStore, evictor: Evictor
) -> None:
    _track(db, clock, library, 1)
    clock.advance(DAY)
    _track(db, clock, library, 0)
    _old(clock)
    _limit(db, clock, 10 * MB)
    assert [c.track_id for c in evictor.plan().candidates] == ["t1", "t0"]


# ---------------------------------------------------------------------- freeing


def test_over_the_limit_frees_the_least_played_down_to_the_low_water_mark(
    db: Database, clock: FakeClock, library: LocalLibraryStore, evictor: Evictor
) -> None:
    for n in range(10):
        _track(db, clock, library, n)
        _play(db, clock, "u1", f"t{n}", n)
    _old(clock)
    # 10 MB against a 9 MB limit: down to 8.1 MB, so two tracks go (one would leave 9 MB).
    _limit(db, clock, 9 * MB)
    plan = evictor.plan()
    assert (plan.over, plan.target_bytes, plan.freed_bytes) == (True, 8_100_000, 2 * MB)
    result = evictor.run_once()
    assert result == evict.RunResult(2, 2 * MB, reached=True)
    assert _freed(db) == {"t0", "t1"}
    assert not (library.root / "Artist/Album/00.opus").exists()
    assert (library.root / "Artist/Album/02.opus").exists()
    assert evictor.plan().over is False
    # A second run has nothing to do.
    assert evictor.run_once().tracks == 0


def test_a_freed_track_keeps_its_row_and_downloads_again(
    db: Database, clock: FakeClock, library: LocalLibraryStore, evictor: Evictor
) -> None:
    _track(db, clock, library, 0)
    _track(db, clock, library, 1)
    _play(db, clock, "u1", "t0", 1)
    _play(db, clock, "u1", "t1", 9)
    now = format_ts(clock.now())
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO playlists (id, owner_id, name, created_at, updated_at)"
            " VALUES ('p1', 'u1', 'Mix', ?, ?)",
            (now, now),
        )
        conn.execute(
            "INSERT INTO playlist_tracks (playlist_id, position, track_id, added_at)"
            " VALUES ('p1', 0, 't0', ?)",
            (now,),
        )
        conn.execute(
            "INSERT INTO jobs (id, kind, track_id, yt_video_id, state, priority, created_at,"
            " updated_at) VALUES ('j0', 'download', 't0', ?, 'ready', 50, ?, ?)",
            (_video(0), now, now),
        )
    _old(clock)
    _limit(db, clock, int(1.5 * MB))
    assert evictor.run_once().tracks == 1
    assert _status(db, "t0") == ("pending", None)
    with db.read() as conn:
        track = conn.execute(
            "SELECT title, yt_video_id, size_bytes, archived_at FROM tracks WHERE id = 't0'"
        ).fetchone()
        plays = conn.execute(
            "SELECT play_count FROM user_track_stats WHERE track_id = 't0'"
        ).scalar()
        entries = conn.execute(
            "SELECT COUNT(*) FROM playlist_tracks WHERE track_id = 't0'"
        ).scalar()
        jobs = conn.execute("SELECT COUNT(*) FROM jobs WHERE track_id = 't0'").scalar()
    assert track is not None
    assert (track["title"], track["yt_video_id"]) == ("Song 0", _video(0))
    assert (track["size_bytes"], track["archived_at"]) == (None, None)
    assert (plays, entries, jobs) == (1, 1, 0)
    # The next play queues a fresh download (an old `ready` job would have been reused).
    job = SqliteJobQueue(db, clock).enqueue(
        track_id="t0", video_id=_video(0), priority=PRIORITY_STREAM
    )
    assert job.state == "queued"


def test_protected_tracks_are_never_freed(
    db: Database, clock: FakeClock, library: LocalLibraryStore, evictor: Evictor
) -> None:
    now = format_ts(clock.now())
    _track(db, clock, library, 0)
    _track(db, clock, library, 1, album="al1")
    _track(db, clock, library, 2, artist="ar1")
    _track(db, clock, library, 3, video=False)
    _track(db, clock, library, 4)
    _track(db, clock, library, 5)
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO starred_tracks (user_id, track_id, starred_at) VALUES ('u2', 't0', ?)",
            (now,),
        )
        conn.execute(
            "INSERT INTO starred_albums (user_id, album_id, starred_at) VALUES ('u1', 'al1', ?)",
            (now,),
        )
        conn.execute(
            "INSERT INTO starred_artists (user_id, artist_id, starred_at) VALUES ('u1', 'ar1', ?)",
            (now,),
        )
        conn.execute(
            "INSERT INTO jobs (id, kind, track_id, yt_video_id, state, priority, lease_id,"
            " lease_expires_at, created_at, updated_at)"
            " VALUES ('j4', 'download', 't4', ?, 'downloading', 100, 'l4', ?, ?, ?)",
            (_video(4), now, now, now),
        )
    _old(clock)
    _track(db, clock, library, 6)  # inside the grace period
    _limit(db, clock, MB)
    plan = evictor.plan()
    assert [c.track_id for c in plan.candidates] == ["t5"]
    assert plan.reachable is False
    result = evictor.run_once()
    assert (result.tracks, result.reached) == (1, False)
    assert _freed(db) == {"t5"}


def test_grace_period_zero_frees_new_tracks(
    db: Database, clock: FakeClock, library: LocalLibraryStore, evictor: Evictor
) -> None:
    _track(db, clock, library, 0)
    _track(db, clock, library, 1)
    clock.advance(1)
    _limit(db, clock, int(1.5 * MB), grace_days=0)
    assert evictor.run_once().tracks == 1


def test_a_star_that_lands_after_planning_wins(
    db: Database, clock: FakeClock, library: LocalLibraryStore, evictor: Evictor
) -> None:
    _track(db, clock, library, 0)
    _track(db, clock, library, 1)
    _old(clock)
    _limit(db, clock, int(1.5 * MB))
    plan = evictor.plan()
    assert [c.track_id for c in plan.candidates] == ["t0"]
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO starred_tracks (user_id, track_id, starred_at) VALUES ('u1', 't0', ?)",
            (format_ts(clock.now()),),
        )
    assert evictor._free(plan.candidates[0], evict._cutoff(clock, plan.policy)) is False
    assert _status(db, "t0")[0] == "ready"
    assert (library.root / "Artist/Album/00.opus").exists()


def test_a_track_taken_meanwhile_is_skipped(
    db: Database,
    clock: FakeClock,
    library: LocalLibraryStore,
    evictor: Evictor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _track(db, clock, library, 0)
    _track(db, clock, library, 1)
    _old(clock)
    _limit(db, clock, int(1.5 * MB))
    monkeypatch.setattr(evictor, "_free", lambda candidate, cutoff: False)
    assert evictor.run_once() == evict.RunResult(0, 0, reached=True)
    assert (library.root / "Artist/Album/00.opus").exists()


def test_a_file_that_cannot_be_removed_is_left(  # noqa: PLR0913, PLR0917 - fixtures
    db: Database,
    clock: FakeClock,
    library: LocalLibraryStore,
    evictor: Evictor,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _track(db, clock, library, 0)
    _track(db, clock, library, 1)
    _old(clock)
    _limit(db, clock, int(1.5 * MB))

    def refuse(path: str) -> None:
        raise PermissionError(path)

    monkeypatch.setattr(library, "delete", refuse)
    with caplog.at_level(logging.WARNING, logger="ultimatetunes.library.evict"):
        result = evictor.run_once()
    assert (result.tracks, result.files_left) == (1, 1)
    assert _status(db, "t0") == ("pending", None)
    assert "left on disk (PermissionError)" in caplog.text


def test_a_run_that_freed_tracks_is_recorded_and_audited(
    db: Database, clock: FakeClock, library: LocalLibraryStore, evictor: Evictor
) -> None:
    _track(db, clock, library, 0)
    _track(db, clock, library, 1)
    _old(clock)
    _limit(db, clock, int(1.5 * MB))
    evictor.run_once()
    with db.read() as conn:
        last = evict.last_run(conn)
        audit = conn.execute(
            "SELECT actor_user_id, action, detail FROM audit_log WHERE action = 'library.evict'"
        ).fetchall()
    assert last == {"at": format_ts(clock.now()), "tracks": 1, "bytes": MB, "reached": True}
    assert len(audit) == 1
    assert audit[0]["actor_user_id"] is None
    assert json.loads(str(audit[0]["detail"])) == {"tracks": 1, "bytes": MB, "reached": True}


def test_an_over_limit_run_with_nothing_to_free_is_recorded_not_audited(
    db: Database,
    clock: FakeClock,
    library: LocalLibraryStore,
    evictor: Evictor,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _track(db, clock, library, 0)
    _track(db, clock, library, 1)
    _limit(db, clock, MB)  # both still in the grace period
    with caplog.at_level(logging.WARNING, logger="ultimatetunes.library.evict"):
        assert evictor.run_once() == evict.RunResult(0, 0, reached=False)
    with db.read() as conn:
        assert evict.last_run(conn) == {
            "at": format_ts(clock.now()),
            "tracks": 0,
            "bytes": 0,
            "reached": False,
        }
        audited = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action = 'library.evict'"
        ).scalar()
    assert audited == 0
    assert "only protected tracks are left" in caplog.text


@pytest.mark.anyio
async def test_run_forever_keeps_going_after_a_failure(
    evictor: Evictor, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[int] = []
    second = anyio.Event()

    def flaky() -> evict.RunResult:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        second.set()
        return evict.RunResult(0, 0, reached=True)

    monkeypatch.setattr(evictor, "run_once", flaky)
    with caplog.at_level(logging.ERROR, logger="ultimatetunes.library.evict"):
        with anyio.move_on_after(1):
            async with anyio.create_task_group() as group:
                group.start_soon(evictor.run_forever, 0.01)
                await second.wait()
                group.cancel_scope.cancel()
    assert len(calls) >= 2
    assert "library limit check failed" in caplog.text
