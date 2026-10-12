# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings of the lyrics area (`UT_LYRICS_*` env vars). Owner: PLAN T10."""

from pydantic import Field

from ultimatetunes.settings import AreaSettings


class LyricsSettings(AreaSettings):
    # Timeout of one LRCLIB request (connect, read, write and pool), seconds.
    lyrics_timeout_s: float = Field(default=5.0, gt=0, le=30)
    # Our own limit towards LRCLIB, shared by every request of this server (token bucket).
    # LRCLIB asks for sequential requests with a short pause between them.
    lyrics_rate_per_s: float = Field(default=1.0, gt=0, le=5)
    lyrics_burst: float = Field(default=2.0, ge=1, le=10)
    # A track LRCLIB has no lyrics for is asked again after this many days (negative cache in
    # the `lyrics` table: LRCLIB fetches missing tracks in the background).
    lyrics_not_found_retry_days: int = Field(default=7, ge=1, le=365)
    # After a failed lookup (timeout, 5xx, unreadable answer) the same track is not asked again
    # for this long (TtlCache), so a client retrying a broken lookup does not hammer LRCLIB.
    lyrics_failure_backoff_s: int = Field(default=300, ge=1, le=86400)
