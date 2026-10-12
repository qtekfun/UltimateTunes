# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""What `complete` does to the library, inside the release transaction (contracts/ids.md).

`registerTrack` (library area) records its decision on the job: a reserved `library_path`, or
`merge_into_track_id` when the recording is already in the library. `complete` applies it:

- **Archived**: the file must be at the reserved path with the registered size; the pending
  track becomes `ready` with its `path` and `archived_at`.
- **Merged**: in one transaction, the `yt:` alias, stars, playlist entries, play history, play
  statistics and import items of the pending track move to the existing track, and the pending
  track becomes `merged` (`merged_into`). No row is deleted except the moved duplicates, so no
  job is ever cascaded away.

Anything that does not match the decision is refused, and the whole `complete` rolls back.
"""

from ultimatetunes.core.storage import LibraryStore, check_relative
from ultimatetunes.db.driver import Connection
from ultimatetunes.errors import Conflict, InvalidStateTransition
from ultimatetunes.jobs.queue import Finalizer, Job


def archive_finalizer(
    library: LibraryStore, *, track_id: str, library_path: str | None, now: str
) -> Finalizer:
    """The `Finalizer` of one `complete` call (`libraryPath` null means merged)."""

    def finalize(conn: Connection, job: Job) -> None:
        if library_path is None:
            _merge(conn, job, track_id, now)
        else:
            _archive(
                conn, job, library, track_id=track_id, path=check_relative(library_path), now=now
            )

    return finalize


def _archive(  # noqa: PLR0913 - the decision and the context of one complete
    conn: Connection, job: Job, library: LibraryStore, *, track_id: str, path: str, now: str
) -> None:
    if job.library_path is None:
        raise InvalidStateTransition("complete needs a registered libraryPath")
    if path != job.library_path or track_id != job.track_id:
        raise Conflict("complete does not match the registration")
    size = conn.execute("SELECT size_bytes FROM tracks WHERE id = ?", (job.track_id,)).scalar()
    if not library.exists(path) or library.size(path) != size:
        raise Conflict("the archived file is missing or has another size")
    conn.execute(
        "UPDATE tracks SET status = 'ready', path = ?, archived_at = ?, updated_at = ?"
        " WHERE id = ?",
        (path, now, now, job.track_id),
    )


def _target(conn: Connection, track_id: str) -> str:
    """The track a merge points at: `merged_into` never points at a merged track (one hop)."""
    row = conn.execute(
        "SELECT status, merged_into FROM tracks WHERE id = ?", (track_id,)
    ).fetchone()
    if row is None:
        raise Conflict("the merge target is gone")
    if row["status"] == "merged" and row["merged_into"] is not None:
        return str(row["merged_into"])
    return track_id


def _merge(conn: Connection, job: Job, track_id: str, now: str) -> None:
    if job.merge_into_track_id is None:
        raise InvalidStateTransition("complete without libraryPath needs a merge decision")
    target = _target(conn, job.merge_into_track_id)
    if track_id not in (job.merge_into_track_id, target):
        raise Conflict("complete does not match the merge decision")
    move_track_references(conn, job.track_id, target)
    conn.execute(
        "UPDATE tracks SET status = 'merged', merged_into = ?, updated_at = ? WHERE id = ?",
        (target, now, job.track_id),
    )


def move_track_references(conn: Connection, source: str, target: str) -> None:
    """Moves every user-facing reference of `source` to `target` (contracts/ids.md). A user who
    starred both keeps one star; play statistics are summed."""
    params = (source,)
    conn.execute("UPDATE track_aliases SET track_id = ? WHERE track_id = ?", (target, source))
    conn.execute(
        "INSERT INTO starred_tracks (user_id, track_id, starred_at)"
        " SELECT s.user_id, ?, s.starred_at FROM starred_tracks s WHERE s.track_id = ?"
        " AND NOT EXISTS (SELECT 1 FROM starred_tracks t"
        " WHERE t.user_id = s.user_id AND t.track_id = ?)",
        (target, source, target),
    )
    conn.execute("DELETE FROM starred_tracks WHERE track_id = ?", params)
    conn.execute("UPDATE playlist_tracks SET track_id = ? WHERE track_id = ?", (target, source))
    conn.execute("UPDATE play_history SET track_id = ? WHERE track_id = ?", (target, source))
    conn.execute("UPDATE import_items SET track_id = ? WHERE track_id = ?", (target, source))
    _merge_stats(conn, source, target)


_SOURCE_STAT = (
    "(SELECT p.{col} FROM user_track_stats p"
    " WHERE p.user_id = user_track_stats.user_id AND p.track_id = ?)"
)


def _merge_stats(conn: Connection, source: str, target: str) -> None:
    count = _SOURCE_STAT.format(col="play_count")
    last = _SOURCE_STAT.format(col="last_played_at")
    # Portable "greatest": neither MAX(a, b) (SQLite) nor GREATEST (PostgreSQL) is shared.
    conn.execute(
        f"UPDATE user_track_stats SET play_count = play_count + {count},"  # noqa: S608  # nosec B608
        f" last_played_at = CASE WHEN {last} IS NOT NULL"
        f" AND (last_played_at IS NULL OR {last} > last_played_at)"
        f" THEN {last} ELSE last_played_at END"
        " WHERE track_id = ? AND user_id IN"
        " (SELECT user_id FROM user_track_stats WHERE track_id = ?)",
        (source, source, source, source, target, source),
    )
    conn.execute(
        "INSERT INTO user_track_stats (user_id, track_id, play_count, last_played_at)"
        " SELECT s.user_id, ?, s.play_count, s.last_played_at FROM user_track_stats s"
        " WHERE s.track_id = ? AND NOT EXISTS (SELECT 1 FROM user_track_stats t"
        " WHERE t.user_id = s.user_id AND t.track_id = ?)",
        (target, source, target),
    )
    conn.execute("DELETE FROM user_track_stats WHERE track_id = ?", (source,))
