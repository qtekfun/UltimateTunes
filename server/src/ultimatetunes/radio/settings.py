# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings of radio (`UT_` env vars)."""

from pydantic import Field

from ultimatetunes.settings import AreaSettings


class RadioSettings(AreaSettings):
    # Off: `/ut/v1/radio` and `getSimilarSongs2` answer `FeatureDisabled` (capability `radio`).
    radio: bool = True
    # Off (or `radio` off): `/ut/v1/recommendations` answers `FeatureDisabled`. Recommendations
    # reuse the YouTube Music watch playlist (radio), so they need `radio` on as well.
    recommendations: bool = True
    # How many of the caller's top/favourite songs seed the recommendations (one radio each).
    recommendation_seeds: int = Field(default=4, ge=1, le=10)
    # Off: `/ut/v1/charts` and `/ut/v1/moods` answer `FeatureDisabled` (capability `charts`).
    # These reuse YouTube Music's own public charts/moods, so they also need `radio` on.
    charts: bool = True
    # Default country for `/ut/v1/charts` (ISO 3166-1 alpha-2; `ZZ` = global). The caller may
    # override it per request.
    charts_country: str = Field(default="ZZ", pattern=r"^[A-Z]{2}$")
    # ListenBrainz recommendation lookups (new outbound host `api.listenbrainz.org`, CC0 data,
    # read-only — no listening history leaves the server). **Off by default**: the owner opts
    # in. Needs `recommendations` (and so `radio`) on. Adds a `listenbrainz` shelf to
    # `/ut/v1/recommendations` with an artist's community-popular recordings matched on YouTube
    # Music; on any failure the rest of the recommendations are still returned.
    listenbrainz_recommendations: bool = False
    # How many of the caller's top/favourite artists (those with a MusicBrainz id) seed the
    # ListenBrainz lookups, and how many popular recordings to take from each.
    listenbrainz_seeds: int = Field(default=1, ge=1, le=5)
    listenbrainz_tracks: int = Field(default=6, ge=1, le=20)
    # Per request to `api.listenbrainz.org`.
    listenbrainz_timeout_s: float = Field(default=5.0, gt=0, le=30)
