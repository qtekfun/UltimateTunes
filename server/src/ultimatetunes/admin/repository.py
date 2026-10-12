# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the admin pages read and change in the database, in portable SQL.

Users, keys and the audit log go through T04's `AuthService`; jobs through `JobQueue`; files
through `LibraryStore`. This module covers the rest: listings for the pages, library deletes
(rows here, files through the store), worker commands, the runtime `settings` table and the
audit entries of panel actions.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass

from ultimatetunes.auth.repository import AuditEntry, AuditRepository, audit_detail
from ultimatetunes.core.clock import Clock, format_ts
from ultimatetunes.db.driver import Connection
from ultimatetunes.db.repository import Repository
from ultimatetunes.errors import Conflict, NotFound
from ultimatetunes.ids import new_id
from ultimatetunes.search.text import like_pattern, normalize

LIST_LIMIT = 200
# Rows per page of the lists that grow without bound (queue, needs review, audit log).
PAGE_SIZE = 50
JOB_STATES = ("queued", "downloading", "tagging", "ready", "failed", "cancelled")
LEASED = ("downloading", "tagging")
WORKER_COMMANDS = ("update_ytdlp", "run_canary")


@dataclass(frozen=True)
class JobRow:
    id: str
    state: str
    priority: int
    attempts: int
    max_attempts: int
    progress: float
    cancel_requested: bool
    error_code: str | None
    error_message: str | None
    yt_video_id: str
    updated_at: str
    title: str
    artist_name: str
    requested_by_name: str | None


@dataclass(frozen=True)
class TrackRow:
    id: str
    title: str
    artist_name: str
    album_name: str | None
    status: str
    size_bytes: int | None


@dataclass(frozen=True)
class AlbumRow:
    id: str
    name: str
    artist: str
    year: int | None
    track_count: int


@dataclass(frozen=True)
class LibraryStats:
    tracks: int
    albums: int
    artists: int
    needs_review: int
    track_bytes: int


@dataclass(frozen=True)
class WorkerRow:
    worker_id: str
    version: str | None
    ytdlp_version: str | None
    last_seen_at: str


@dataclass(frozen=True)
class CanaryRow:
    source: str
    worker_id: str | None
    ytdlp_version: str | None
    ran_at: str
    ok: bool
    message: str | None


@dataclass(frozen=True)
class CommandRow:
    command: str
    created_at: str
    delivered_at: str | None
    delivered_to: str | None


@dataclass(frozen=True)
class UserUsage:
    """One user's share of the download limits (core/limits.py, jobs/gate.py)."""

    active_jobs: int
    bytes_24h: int


@dataclass(frozen=True)
class Deleted:
    """What a library delete removed: files to delete through the store, and counts."""

    paths: list[str]
    tracks: int


_JOBS = (
    "SELECT j.id, j.state, j.priority, j.attempts, j.max_attempts, j.progress,"
    " j.cancel_requested, j.error_code, j.error_message, j.yt_video_id, j.updated_at,"
    " t.title, t.artist_name, u.username AS requested_by_name"
    " FROM jobs j JOIN tracks t ON t.id = j.track_id LEFT JOIN users u ON u.id = j.requested_by"
)
_AUDIT = (
    "SELECT id, occurred_at, actor_user_id, actor_ip, action, target_type, target_id, detail"
    " FROM audit_log"
)


def _int(value: object) -> int:
    if isinstance(value, int):
        return value
    raise TypeError(f"expected an integer column, got {type(value).__name__}")


def _opt(value: object) -> str | None:
    return None if value is None else str(value)


class AdminRepository(Repository):
    # ------------------------------------------------------------------ jobs

    def jobs(self, state: str | None, limit: int = LIST_LIMIT, offset: int = 0) -> list[JobRow]:
        if state is None:
            return self.all(
                JobRow,
                _JOBS + " ORDER BY j.updated_at DESC, j.id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        return self.all(
            JobRow,
            _JOBS + " WHERE j.state = ? ORDER BY j.updated_at DESC, j.id DESC LIMIT ? OFFSET ?",
            (state, limit, offset),
        )

    def job_counts(self) -> dict[str, int]:
        rows = self.conn.execute("SELECT state, COUNT(*) AS n FROM jobs GROUP BY state").fetchall()
        counts = dict.fromkeys(JOB_STATES, 0)
        counts.update({str(row["state"]): _int(row["n"]) for row in rows})
        return counts

    # ------------------------------------------------------------------ library

    def stats(self) -> LibraryStats:
        row = self.conn.execute(
            "SELECT (SELECT COUNT(*) FROM tracks WHERE status = 'ready') AS tracks,"
            " (SELECT COUNT(*) FROM albums) AS albums,"
            " (SELECT COUNT(*) FROM artists) AS artists,"
            " (SELECT COUNT(*) FROM tracks WHERE needs_review = 1) AS needs_review,"
            " (SELECT COALESCE(SUM(size_bytes), 0) FROM tracks WHERE status = 'ready')"
            " AS track_bytes"
        ).fetchone()
        if row is None:  # pragma: no cover - an aggregate always returns one row
            raise RuntimeError("library statistics returned no row")
        return LibraryStats(
            _int(row["tracks"]),
            _int(row["albums"]),
            _int(row["artists"]),
            _int(row["needs_review"]),
            _int(row["track_bytes"]),
        )

    def needs_review(self, limit: int = LIST_LIMIT, offset: int = 0) -> list[TrackRow]:
        return self.all(
            TrackRow,
            "SELECT id, title, artist_name, album_name, status, size_bytes FROM tracks"
            " WHERE needs_review = 1 ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )

    def mark_reviewed(self, track_id: str, now: str) -> None:
        """Clears `needs_review` once the admin checked the track's metadata."""
        if not self.run(
            "UPDATE tracks SET needs_review = 0, updated_at = ? WHERE id = ? AND needs_review = 1",
            (now, track_id),
        ):
            raise NotFound("No such track needs review")

    def find_tracks(self, query: str, limit: int = LIST_LIMIT) -> list[TrackRow]:
        """Tracks whose normalised title contains the normalised query."""
        return self.all(
            TrackRow,
            "SELECT id, title, artist_name, album_name, status, size_bytes FROM tracks"
            " WHERE status <> 'merged' AND title_norm LIKE ? ESCAPE '\\'"
            " ORDER BY title_norm, id LIMIT ?",
            (like_pattern(normalize(query)), limit),
        )

    def find_albums(self, query: str, limit: int = LIST_LIMIT) -> list[AlbumRow]:
        """Albums whose normalised name contains the normalised query."""
        return self.all(
            AlbumRow,
            "SELECT a.id, a.name, ar.name AS artist, a.year, COUNT(t.id) AS track_count"
            " FROM albums a JOIN artists ar ON ar.id = a.artist_id"
            " LEFT JOIN tracks t ON t.album_id = a.id WHERE a.name_norm LIKE ? ESCAPE '\\'"
            " GROUP BY a.id, a.name, ar.name, a.year, a.name_norm ORDER BY a.name_norm, a.id"
            " LIMIT ?",
            (like_pattern(normalize(query)), limit),
        )

    def delete_track(self, track_id: str) -> Deleted:
        row = self.conn.execute("SELECT path FROM tracks WHERE id = ?", (track_id,)).fetchone()
        if row is None:
            raise NotFound("No such track")
        playlists = self._playlists_of([track_id])
        self._delete_track_row(track_id)
        self._renumber(playlists)
        return Deleted([str(row["path"])] if row["path"] else [], 1)

    def delete_album(self, album_id: str) -> Deleted:
        album = self.conn.execute(
            "SELECT cover_path FROM albums WHERE id = ?", (album_id,)
        ).fetchone()
        if album is None:
            raise NotFound("No such album")
        tracks = self.conn.execute(
            "SELECT id, path FROM tracks WHERE album_id = ? ORDER BY id", (album_id,)
        ).fetchall()
        ids = [str(t["id"]) for t in tracks]
        playlists = self._playlists_of(ids)
        # Tracks merged into one of these keep their row; merged_into becomes NULL.
        for track_id in ids:
            self._delete_track_row(track_id)
        # Only once no track points at it (a track added meanwhile keeps the album).
        if not self.run(
            "DELETE FROM albums WHERE id = ? AND NOT EXISTS"
            " (SELECT 1 FROM tracks WHERE album_id = ?)",
            (album_id, album_id),
        ):
            raise Conflict("The album changed meanwhile; try again")
        self._renumber(playlists)
        paths = [str(t["path"]) for t in tracks if t["path"]]
        if album["cover_path"]:
            paths.append(str(album["cover_path"]))
        return Deleted(paths, len(tracks))

    def _delete_track_row(self, track_id: str) -> None:
        """A job row is never deleted while it holds a lease (0001_init.sql). Two statements,
        each re-checking the lease itself, so a concurrent claim on PostgreSQL (READ COMMITTED)
        is seen: the job rows not leased go first (a row a claimer just leased is re-checked and
        kept), then the track only while no job of it, or merging into it, is leased (a new
        statement, a new snapshot). Nothing is read and then acted on."""
        self.run(
            "DELETE FROM jobs WHERE track_id = ? AND state NOT IN ('downloading', 'tagging')",
            (track_id,),
        )
        deleted = self.run(
            "DELETE FROM tracks WHERE id = ? AND NOT EXISTS (SELECT 1 FROM jobs"
            " WHERE state IN ('downloading', 'tagging')"
            " AND (track_id = ? OR merge_into_track_id = ?))",
            (track_id, track_id, track_id),
        )
        if deleted != 1:
            raise Conflict("A download of this item is in progress; cancel it first")

    def _playlists_of(self, track_ids: Sequence[str]) -> list[str]:
        playlists: set[str] = set()
        for track_id in track_ids:
            rows = self.conn.execute(
                "SELECT DISTINCT playlist_id FROM playlist_tracks WHERE track_id = ?", (track_id,)
            ).fetchall()
            playlists.update(str(row["playlist_id"]) for row in rows)
        return sorted(playlists)

    def _renumber(self, playlist_ids: Sequence[str]) -> None:
        """Positions stay 0-based and dense: delete and reinsert (0001_init.sql)."""
        for playlist_id in playlist_ids:
            entries = self.conn.execute(
                "SELECT track_id, added_at FROM playlist_tracks WHERE playlist_id = ?"
                " ORDER BY position",
                (playlist_id,),
            ).fetchall()
            self.run("DELETE FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,))
            for position, entry in enumerate(entries):
                self.run(
                    "INSERT INTO playlist_tracks (playlist_id, position, track_id, added_at)"
                    " VALUES (?, ?, ?, ?)",
                    (playlist_id, position, entry["track_id"], entry["added_at"]),
                )

    # ------------------------------------------------------------------ download usage

    def user_usage(self, since_hour: str) -> dict[str, UserUsage]:
        """Per user: jobs queued or running, and bytes charged since `since_hour` (the gate's
        24-hour window). Users with neither are left out."""
        active = self.conn.execute(
            "SELECT requested_by, COUNT(*) AS n FROM jobs WHERE requested_by IS NOT NULL"
            " AND state IN ('queued', 'downloading', 'tagging') GROUP BY requested_by"
        ).fetchall()
        spent = self.conn.execute(
            "SELECT user_id, SUM(bytes) AS n FROM download_usage WHERE hour_start >= ?"
            " GROUP BY user_id",
            (since_hour,),
        ).fetchall()
        jobs = {str(r["requested_by"]): _int(r["n"]) for r in active}
        used = {str(r["user_id"]): _int(r["n"]) for r in spent}
        return {
            user: UserUsage(jobs.get(user, 0), used.get(user, 0))
            for user in sorted(set(jobs) | set(used))
        }

    # ------------------------------------------------------------------ audit log

    def audit_entries(
        self, action: str | None, actor_id: str | None, limit: int, offset: int = 0
    ) -> list[AuditEntry]:
        """The audit log, newest first, optionally of one action and one actor."""
        where: list[str] = []
        params: list[object] = []
        if action:
            where.append("action = ?")
            params.append(action)
        if actor_id:
            where.append("actor_user_id = ?")
            params.append(actor_id)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        return self.all(
            AuditEntry,
            _AUDIT + clause + " ORDER BY occurred_at DESC, id DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )

    def audit_actions(self) -> list[str]:
        rows = self.conn.execute("SELECT DISTINCT action FROM audit_log ORDER BY action").fetchall()
        return [str(r["action"]) for r in rows]

    # ------------------------------------------------------------------ workers and canary

    def workers(self) -> list[WorkerRow]:
        return self.all(
            WorkerRow,
            "SELECT worker_id, version, ytdlp_version, last_seen_at FROM worker_status"
            " ORDER BY last_seen_at DESC, worker_id",
        )

    def canary_runs(self, limit: int = 10) -> list[CanaryRow]:
        return self.all(
            CanaryRow,
            "SELECT source, worker_id, ytdlp_version, ran_at, ok, message FROM canary_runs"
            " ORDER BY ran_at DESC, id DESC LIMIT ?",
            (limit,),
        )

    def commands(self, limit: int = 10) -> list[CommandRow]:
        return self.all(
            CommandRow,
            "SELECT command, created_at, delivered_at, delivered_to FROM worker_commands"
            " ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        )

    def add_command(self, command: str, requested_by: str, clock: Clock) -> bool:
        """Queues a command for the next worker that reports. False when the same command is
        still waiting (no duplicates)."""
        if command not in WORKER_COMMANDS:
            raise NotFound("No such command")
        waiting = self.conn.execute(
            "SELECT COUNT(*) AS n FROM worker_commands WHERE command = ? AND delivered_at IS NULL",
            (command,),
        ).fetchone()
        if waiting is not None and _int(waiting["n"]) > 0:
            return False
        self.run(
            "INSERT INTO worker_commands (id, command, worker_id, requested_by, created_at)"
            " VALUES (?, ?, NULL, ?, ?)",
            (new_id(clock), command, requested_by, format_ts(clock.now())),
        )
        return True

    # ------------------------------------------------------------------ settings table

    def setting(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def put_setting(self, key: str, value: str, now: str) -> None:
        if self.run(
            "UPDATE settings SET value = ?, updated_at = ? WHERE key = ?", (value, now, key)
        ):
            return
        self.run(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)", (key, value, now)
        )

    def swap_setting(self, key: str, old: str, new: str, now: str) -> bool:
        """Compare and set: True when `key` still held `old` (one replica wins)."""
        return (
            self.run(
                "UPDATE settings SET value = ?, updated_at = ? WHERE key = ? AND value = ?",
                (new, now, key, old),
            )
            == 1
        )

    def delete_setting(self, key: str) -> None:
        self.run("DELETE FROM settings WHERE key = ?", (key,))

    # ------------------------------------------------------------------ notification events

    def failed_jobs_between(self, after: str, until: str) -> list[tuple[str, str, str | None]]:
        rows = self.conn.execute(
            "SELECT t.title, t.artist_name, j.error_code FROM jobs j"
            " JOIN tracks t ON t.id = j.track_id WHERE j.state = 'failed'"
            " AND j.finished_at > ? AND j.finished_at <= ? ORDER BY j.finished_at, j.id",
            (after, until),
        ).fetchall()
        return [(str(r["title"]), str(r["artist_name"]), _opt(r["error_code"])) for r in rows]

    def failed_canaries_between(self, after: str, until: str) -> list[tuple[str, str | None]]:
        rows = self.conn.execute(
            "SELECT source, message FROM canary_runs WHERE ok = 0 AND ran_at > ? AND ran_at <= ?"
            " ORDER BY ran_at, id",
            (after, until),
        ).fetchall()
        return [(str(r["source"]), _opt(r["message"])) for r in rows]


def audit(  # noqa: PLR0913 - the columns of one audit entry
    conn: Connection,
    clock: Clock,
    *,
    actor_id: str,
    ip: str | None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict[str, object] | None = None,
) -> None:
    """An audit entry for a panel action, in the caller's transaction. No secrets in `detail`."""
    AuditRepository(conn).add(
        AuditEntry(
            id=new_id(clock),
            occurred_at=format_ts(clock.now()),
            actor_user_id=actor_id,
            actor_ip=ip,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=audit_detail(detail),
        )
    )


def detail_text(detail: str | None) -> str:
    """An audit detail (JSON as TEXT) as short `key=value` text for the audit page."""
    if not detail:
        return ""
    try:
        values = json.loads(detail)
    except ValueError:
        return detail
    if not isinstance(values, dict):
        return detail
    return ", ".join(f"{k}={v}" for k, v in values.items())
