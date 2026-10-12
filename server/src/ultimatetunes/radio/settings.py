# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings of radio (`UT_` env vars)."""

from ultimatetunes.settings import AreaSettings


class RadioSettings(AreaSettings):
    # Off: `/ut/v1/radio` and `getSimilarSongs2` answer `FeatureDisabled` (capability `radio`).
    radio: bool = True
