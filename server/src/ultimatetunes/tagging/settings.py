# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings of the tagging and archive step (`UT_*` env vars). Owner: PLAN T09."""

from pathlib import Path

from pydantic import Field

from ultimatetunes.settings import AreaSettings


class TaggingSettings(AreaSettings):
    # Debian's ffmpeg in the image (Dockerfile). Called with argument lists only.
    ffmpeg_path: Path = Path("/usr/bin/ffmpeg")
    ffprobe_path: Path = Path("/usr/bin/ffprobe")
    # Bound of one ffmpeg/ffprobe run (remux, loudness of one track or a whole album).
    ffmpeg_timeout_s: float = Field(default=300.0, gt=0)
    # MusicBrainz lookup and Cover Art Archive (RF-04). Off: YouTube Music data only, and
    # every track is marked `needs_review`.
    musicbrainz_enabled: bool = True
    # A MusicBrainz candidate scoring below this keeps the YouTube Music data and sets
    # `needs_review` (scores in [0, 1], see `tagging/matching.py`).
    musicbrainz_min_score: float = Field(default=0.85, ge=0, le=1)
    # Timeout of one outbound request (MusicBrainz, Cover Art Archive, YouTube thumbnail).
    metadata_timeout_s: float = Field(default=15.0, gt=0, le=120)
    # Covers: Cover Art Archive first, then the YouTube thumbnail (contracts/ids.md).
    covers_enabled: bool = True
