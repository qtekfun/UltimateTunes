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
