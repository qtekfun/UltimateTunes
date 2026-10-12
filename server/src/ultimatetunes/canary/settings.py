# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings of the canary area (`UT_CANARY_*` env vars). Owner: PLAN T19.

The canary exercises YouTube Music and yt-dlp with fixed targets (docs/compat.md, "Canary
track"): one search, one radio, one album page and one playlist read in the api, one download
in the worker. Defaults point at a Creative Commons (CC BY 4.0) track by Kevin MacLeod on his
official channel; an admin can point them elsewhere if it ever disappears. With
`UT_FAKE_YOUTUBE` the targets of the fake catalog are used instead (test stack).
"""

from pathlib import Path

from pydantic import Field

from ultimatetunes.settings import AreaSettings

VIDEO_ID_PATTERN = r"^[A-Za-z0-9_-]{11}$"
PLAYLIST_ID_PATTERN = r"^[A-Za-z0-9_-]{2,64}$"


class CanarySettings(AreaSettings):
    # Scheduled runs (api and worker). The admin's "run the canary now" works either way.
    canary_enabled: bool = True
    canary_interval_h: float = Field(default=24.0, gt=0)
    # Wait after start before the first scheduled check (the api remembers its last run in
    # the database; the worker in `canary_state_file`).
    canary_first_delay_s: float = Field(default=120.0, ge=0)
    # How often the api looks for a due run or an admin request.
    canary_poll_s: float = Field(default=60.0, gt=0)
    # Bound of one check (a catalog call, or the whole download).
    canary_timeout_s: float = Field(default=300.0, gt=0)
    # The fixed Creative Commons track (docs/compat.md) and what the catalog checks ask for.
    canary_video_id: str = Field(default="6pEWHaIhxOg", pattern=VIDEO_ID_PATTERN)
    canary_query: str = Field(
        default="Kevin MacLeod Sauropod Spotting", min_length=1, max_length=200
    )
    canary_playlist_id: str = Field(
        default="PLx53r85FKaLyGUec4f9LJUXuCfrFRUV15", pattern=PLAYLIST_ID_PATTERN
    )
    # Worker only: when its last canary ran (it has no database). In the yt-dlp volume, which
    # is the worker's own persistent volume; unwritable means "remember until restart".
    canary_state_file: Path = Path("/opt/ytdlp/canary-state.json")
