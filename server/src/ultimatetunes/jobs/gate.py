# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`DownloadGate`: what a new download must pass before it is queued (SECURITY.md, abuse limits).

`SqliteJobQueue` asks it whenever a request would start a download (a new job, or a failed or
cancelled one queued again), inside the request's write transaction, so a refusal rolls back
everything the request wrote (the pending track and its alias too). In order:

1. the track's duration (from its catalog record) is at most `UT_MAX_TRACK_DURATION_S`:
   otherwise `InvalidParameter` (a permanent answer);
2. `/music` and `/staging` each have at least `UT_MIN_FREE_BYTES` free: otherwise `RateLimited`
   (retry later); `claim` also hands out nothing while space is low;
3. for a request made by a user: fewer than `UT_MAX_QUEUED_JOBS_PER_USER` of the user's jobs are
   queued or running, and the user's jobs touched in the last 24 hours downloaded fewer than
   `UT_MAX_DOWNLOAD_BYTES_PER_DAY_PER_USER` bytes: otherwise `RateLimited`.

Requests without a user (none today) skip step 3 only.
"""

import logging
from collections.abc import Sequence
from datetime import timedelta

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
_ACTIVE = "('queued', 'downloading', 'tagging')"


class DownloadGate:
    def __init__(
        self, limits: DownloadLimits, clock: Clock, stores: Sequence[FileStore] = ()
    ) -> None:
        self._limits = limits
        self._clock = clock
        self._stores = tuple(stores)

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

    def check_space(self) -> None:
        if not self.has_space():
            log.warning("downloads paused: less than UT_MIN_FREE_BYTES free on /music or /staging")
            raise RateLimited(RETRY_SPACE_S, "The server is low on disk space")

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
        since = format_ts(self._clock.now() - DAY)
        spent = conn.execute(
            "SELECT SUM(COALESCE(bytes_downloaded, 0)) FROM jobs"
            " WHERE requested_by = ? AND updated_at >= ?",
            (user_id, since),
        ).scalar()
        if int(str(spent or 0)) >= self._limits.max_download_bytes_per_day_per_user:
            log.info("download refused: a user reached UT_MAX_DOWNLOAD_BYTES_PER_DAY_PER_USER")
            raise RateLimited(RETRY_BYTES_S, "This account's daily download allowance is used up")
