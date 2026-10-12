# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings of streaming while downloading (`UT_*` env vars). Owner: PLAN T16."""

from pydantic import Field

from ultimatetunes.settings import AreaSettings


class StreamingSettings(AreaSettings):
    # Listener caps of an in-flight `yt:` stream (contracts/errors.md): beyond them, HTTP 503.
    max_listeners_per_job: int = Field(default=8, ge=1)
    max_listeners_per_key: int = Field(default=4, ge=1)
