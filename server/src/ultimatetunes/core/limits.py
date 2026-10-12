# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounds on downloads (SECURITY.md, abuse limits): shared by the api and the worker.

- `UT_MAX_TRACK_DURATION_S` (default 1800): a song longer than this is never materialized or
  queued (the api checks the catalog duration), and yt-dlp refuses it again with
  `--match-filter "duration<=N"` (which also refuses live streams, whose duration is unknown).
- `UT_MAX_DOWNLOAD_BYTES` (default 200 MiB): yt-dlp's `--max-filesize`, and the worker stops a
  download that grows past it.
- `UT_MAX_QUEUED_JOBS_PER_USER` (default 200): queued or running downloads one user may have.
- `UT_MAX_DOWNLOAD_BYTES_PER_DAY_PER_USER` (default 5 GiB): bytes of the downloads one user
  requested over the last 24 hours (rolling).
- `UT_MIN_FREE_BYTES` (default 2 GiB): below this much free space on `/music` or `/staging`
  nothing new is queued and no job is claimed.

Variable names are not used by any other area (`settings.py`, area rule).
"""

from pydantic import Field

from ultimatetunes.settings import AreaSettings

MIB = 1024 * 1024
GIB = 1024 * MIB


class DownloadLimits(AreaSettings):
    max_track_duration_s: int = Field(default=1800, ge=60, le=6 * 3600)
    max_download_bytes: int = Field(default=200 * MIB, ge=MIB)
    max_queued_jobs_per_user: int = Field(default=200, ge=1)
    max_download_bytes_per_day_per_user: int = Field(default=5 * GIB, ge=MIB)
    min_free_bytes: int = Field(default=2 * GIB, ge=0)

    def too_long(self, duration_s: float | None) -> bool:
        """True when a known duration is over the limit (an unknown one is left to yt-dlp)."""
        return duration_s is not None and duration_s > self.max_track_duration_s
