# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Requeue downloads that were cut off (`ultimatetunes refetch-failed`).

Two kinds of damage a truncated download can leave (SPEC section 11, fix/ytdlp-403-and-truncated):

- a **failed** download: a 403/`network_error` cut the fetch short, so the job ended `failed`
  and its track with it; nothing was archived. These are requeued through the proven
  `JobQueue.enqueue` path (failed -> queued, attempts reset, track pending again);
- with `--truncated`, a **`ready`** track whose archived file on disk is shorter than (or
  missing against) the recorded `size_bytes`: a half song from before the download boundary
  checked the size. The track is reset to `pending`, the broken file is deleted (it is being
  replaced), its old `ready` job row is dropped and a fresh download is enqueued.

Only requeues; it never deletes a file that is not already shorter than it should be, and a
re-download replaces the one it does delete. Idempotent: a track already `pending`/queued is
left alone. Runs where the database and `/music` are (the api role), never the worker.
"""

import logging
from dataclasses import dataclass

from ultimatetunes.core.clock import Clock, format_ts
from ultimatetunes.core.storage import LibraryStore
from ultimatetunes.db.database import Database
from ultimatetunes.errors import PathRejected
from ultimatetunes.jobs.queue import PRIORITY_KEEP, JobQueue

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Failed:
    track_id: str
    video_id: str
    priority: int


@dataclass(frozen=True)
class _Truncated:
    track_id: str
    video_id: str
    path: str
    recorded_size: int
    actual_size: int | None  # None: the file is gone


@dataclass(frozen=True)
class RefetchResult:
    """What a run requeued (or, with `dry_run`, would requeue)."""

    failed: int
    truncated: int

    @property
    def total(self) -> int:
        return self.failed + self.truncated


# Columns kept when a `ready` track goes back to `pending` (title, artist, album, ids) and the
# ones cleared (everything about the archived file): a re-download re-matches and re-archives.
_RESET_TRACK = (
    "UPDATE tracks SET status = 'pending', path = NULL, format = NULL, content_type = NULL,"
    " size_bytes = NULL, bit_rate_kbps = NULL, sample_rate_hz = NULL, channels = NULL,"
    " rg_track_gain_db = NULL, rg_track_peak = NULL, rg_album_gain_db = NULL,"
    " rg_album_peak = NULL, needs_review = 0, archived_at = NULL, updated_at = ?"
    " WHERE id = ? AND status = 'ready'"
)


class Refetcher:
    def __init__(self, db: Database, jobs: JobQueue, library: LibraryStore, clock: Clock) -> None:
        self._db = db
        self._jobs = jobs
        self._library = library
        self._clock = clock

    # ------------------------------------------------------------ discovery

    def _find_failed(self) -> list[_Failed]:
        with self._db.read() as conn:
            rows = conn.execute(
                "SELECT track_id, yt_video_id, priority FROM jobs"
                " WHERE kind = 'download' AND state = 'failed'"
                " ORDER BY updated_at ASC, id ASC"
            ).fetchall()
        return [
            _Failed(str(r["track_id"]), str(r["yt_video_id"]), int(str(r["priority"])))
            for r in rows
        ]

    def _find_truncated(self) -> list[_Truncated]:
        with self._db.read() as conn:
            rows = conn.execute(
                "SELECT id, yt_video_id, path, size_bytes FROM tracks"
                " WHERE status = 'ready' AND path IS NOT NULL AND size_bytes IS NOT NULL"
                " AND yt_video_id IS NOT NULL ORDER BY id ASC"
            ).fetchall()
        truncated: list[_Truncated] = []
        for row in rows:
            path, recorded = str(row["path"]), int(str(row["size_bytes"]))
            try:
                actual: int | None = self._library.size(path)
            except (OSError, PathRejected):
                actual = None
            if actual != recorded:
                truncated.append(
                    _Truncated(str(row["id"]), str(row["yt_video_id"]), path, recorded, actual)
                )
        return truncated

    # ------------------------------------------------------------ run

    def refetch(self, *, truncated: bool, dry_run: bool) -> RefetchResult:
        failed = self._find_failed()
        broken = self._find_truncated() if truncated else []
        if not dry_run:
            for failed_item in failed:
                self._requeue_failed(failed_item)
            for broken_item in broken:
                self._requeue_truncated(broken_item)
        return RefetchResult(failed=len(failed), truncated=len(broken))

    def _requeue_failed(self, item: _Failed) -> None:
        # The proven requeue path: a `failed` job goes back to `queued`, attempts reset, its
        # track `pending` again. `enqueue` is a no-op if it was requeued meanwhile (idempotent).
        self._jobs.enqueue(
            track_id=item.track_id,
            video_id=item.video_id,
            priority=max(item.priority, PRIORITY_KEEP),
        )
        log.info("refetch: requeued failed download of track %s", item.track_id)

    def _requeue_truncated(self, item: _Truncated) -> None:
        now = format_ts(self._clock.now())
        with self._db.transaction() as conn:
            changed = conn.execute(_RESET_TRACK, (now, item.track_id)).rowcount
            if changed != 1:
                # It was reset or re-requested between discovery and now: leave it to that run.
                return
            conn.execute(
                "DELETE FROM jobs WHERE kind = 'download' AND track_id = ?", (item.track_id,)
            )
        # The track no longer points at the file; delete the broken one so the re-download can
        # take its path (the replacement has another hash and would otherwise conflict).
        try:
            self._library.delete(item.path)
        except (OSError, PathRejected):
            log.warning("refetch: could not delete the truncated file %s", item.path)
        self._jobs.enqueue(track_id=item.track_id, video_id=item.video_id, priority=PRIORITY_KEEP)
        log.info(
            "refetch: track %s had %s bytes on disk, expected %d; requeued",
            item.track_id,
            "no file" if item.actual_size is None else str(item.actual_size),
            item.recorded_size,
        )
