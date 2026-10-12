# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`DownloadGate`: the abuse limits of downloads (SECURITY.md, core/limits.py).

`SqliteJobQueue` asks it whenever a request would start a download (a new job, or a failed or
cancelled one queued again), inside the request's write transaction, so a refusal rolls back
everything the request wrote (the pending track and its alias too). In order:

1. the track's duration (from its catalog record) is at most `UT_MAX_TRACK_DURATION_S`:
   otherwise `InvalidParameter` (a permanent answer);
2. `/music` and `/staging` each have at least `UT_MIN_FREE_BYTES` free: otherwise `RateLimited`
   (retry later);
3. for a request made by a user: fewer than `UT_MAX_QUEUED_JOBS_PER_USER` of the user's jobs are
   queued or running, and the user was charged fewer than
   `UT_MAX_DOWNLOAD_BYTES_PER_DAY_PER_USER` bytes over the last 24 hours: otherwise
   `RateLimited`. Requests without a user skip this step only.

Bytes are charged as they are downloaded (`charge`, from every progress report): to the user who
requested the job at that moment, in one `download_usage` row per user and UTC hour. A retried
attempt adds to the count (it never starts again), and a job queued again by someone else
leaves the bytes already downloaded with the first user.

`claim` (`claimable_sql`) skips the jobs of users over their daily bytes, so queuing many jobs
before the first one finishes cannot overshoot by more than the jobs already running, and hands
out nothing at all while space is low. The low-space state is kept in the `settings` table
(`LOW_DISK_KEY`, the moment it began): it is logged once when it starts and once when it ends,
reported by the admin notifications (admin/notify.py) and shown in the `/readyz` detail.
"""

import logging
from collections.abc import Sequence
from datetime import datetime, timedelta

from ultimatetunes.core.clock import Clock, format_ts
from ultimatetunes.core.limits import DownloadLimits
from ultimatetunes.core.storage import FileStore
from ultimatetunes.db.driver import Connection
from ultimatetunes.errors import InvalidParameter, RateLimited

log = logging.getLogger(__name__)

# Retry-After of each refusal.
RETRY_SPACE_S = 600
RETRY_QUEUED_S = 60
RETRY_BYTES_S = 3600
DAY = timedelta(hours=24)
# Usage rows older than this are deleted when a user's next hour starts.
KEEP_USAGE = timedelta(hours=48)
LOW_DISK_KEY = "downloads.low_disk_since"
_ACTIVE = "('queued', 'downloading', 'tagging')"


def hour_start(moment: datetime) -> str:
    return format_ts(moment.replace(minute=0, second=0, microsecond=0))


class DownloadGate:
    def __init__(
        self, limits: DownloadLimits, clock: Clock, stores: Sequence[FileStore] = ()
    ) -> None:
        self._limits = limits
        self._clock = clock
        self._stores = tuple(stores)

    # ------------------------------------------------------------------ disk space

    def has_space(self) -> bool:
        """Every store has at least `UT_MIN_FREE_BYTES` free (a store that cannot say is full)."""
        minimum = self._limits.min_free_bytes
        for store in self._stores:
            try:
                free = store.free_bytes()
            except OSError:
                return False
            if free < minimum:
                return False
        return True

    def note_space(self, conn: Connection) -> bool:
        """`has_space`, recording a change of state (logged once each way, module doc)."""
        ok = self.has_space()
        since = conn.execute("SELECT value FROM settings WHERE key = ?", (LOW_DISK_KEY,)).scalar()
        if not ok and since is None:
            now = format_ts(self._clock.now())
            conn.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                (LOW_DISK_KEY, now, now),
            )
            log.warning("downloads paused: less than UT_MIN_FREE_BYTES free on /music or /staging")
        elif ok and since is not None:
            conn.execute("DELETE FROM settings WHERE key = ?", (LOW_DISK_KEY,))
            log.warning("downloads resumed: free space is back above UT_MIN_FREE_BYTES")
        return ok

    def check_space(self) -> None:
        # Not recorded here: a refusal rolls the request's transaction back. `claim` records it.
        if not self.has_space():
            raise RateLimited(RETRY_SPACE_S, "The server is low on disk space")

    # ------------------------------------------------------------------ requests

    def check_duration(self, duration_s: float | None) -> None:
        if self._limits.too_long(duration_s):
            raise InvalidParameter(
                f"Songs longer than {self._limits.max_track_duration_s} seconds are not"
                " downloaded by this server"
            )

    def check_new_download(self, conn: Connection, track_id: str, requested_by: str | None) -> None:
        """Raises unless a download of `track_id` for `requested_by` may start now."""
        duration_ms = conn.execute(
            "SELECT duration_ms FROM tracks WHERE id = ?", (track_id,)
        ).scalar()
        self.check_duration(None if duration_ms is None else int(str(duration_ms)) / 1000)
        self.check_space()
        if requested_by is not None:
            self._check_user(conn, requested_by)

    def _check_user(self, conn: Connection, user_id: str) -> None:
        active = conn.execute(
            f"SELECT COUNT(*) FROM jobs WHERE requested_by = ? AND state IN {_ACTIVE}",  # noqa: S608  # nosec B608
            (user_id,),
        ).scalar()
        if int(str(active or 0)) >= self._limits.max_queued_jobs_per_user:
            log.info("download refused: a user reached UT_MAX_QUEUED_JOBS_PER_USER")
            raise RateLimited(RETRY_QUEUED_S, "Too many downloads queued for this account")
        spent = conn.execute(
            "SELECT SUM(bytes) FROM download_usage WHERE user_id = ? AND hour_start >= ?",
            (user_id, self._window_start()),
        ).scalar()
        if int(str(spent or 0)) >= self._limits.max_download_bytes_per_day_per_user:
            log.info("download refused: a user reached UT_MAX_DOWNLOAD_BYTES_PER_DAY_PER_USER")
            raise RateLimited(RETRY_BYTES_S, "This account's daily download allowance is used up")

    def _window_start(self) -> str:
        """The first hour row inside the last 24 hours."""
        return hour_start(self._clock.now() - DAY + timedelta(hours=1))

    # ------------------------------------------------------------------ claims and progress

    def claimable_sql(self) -> tuple[str, tuple[object, ...]]:
        """A condition on `jobs` (and its parameters): the requester is not over its bytes."""
        return (
            " AND (requested_by IS NULL OR requested_by NOT IN (SELECT user_id FROM"
            " download_usage WHERE hour_start >= ? GROUP BY user_id HAVING SUM(bytes) >= ?))",
            (self._window_start(), self._limits.max_download_bytes_per_day_per_user),
        )

    def charge(self, conn: Connection, job_id: str, delta: int) -> None:
        """Charges `delta` downloaded bytes of `job_id` to its requester (module doc)."""
        if delta <= 0:
            return
        user = conn.execute("SELECT requested_by FROM jobs WHERE id = ?", (job_id,)).scalar()
        if user is None:
            return
        now = self._clock.now()
        hour = hour_start(now)
        if conn.execute(
            "UPDATE download_usage SET bytes = bytes + ? WHERE user_id = ? AND hour_start = ?",
            (delta, user, hour),
        ).rowcount:
            return
        conn.execute(
            "DELETE FROM download_usage WHERE user_id = ? AND hour_start < ?",
            (user, hour_start(now - KEEP_USAGE)),
        )
        conn.execute(
            "INSERT INTO download_usage (user_id, hour_start, bytes) VALUES (?, ?, ?)",
            (user, hour, delta),
        )
