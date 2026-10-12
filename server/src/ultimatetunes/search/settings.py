# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings of search and the YouTube Music catalog (`UT_` env vars; SPEC §11, T03b)."""

from pydantic import Field

from ultimatetunes.settings import AreaSettings


class SearchSettings(AreaSettings):
    # Off: search answers from the library only (the admin's switch, capability externalSearch).
    external_search: bool = True
    # `search3` waits this long for YouTube Music, then answers with the library only.
    search_external_timeout_s: float = Field(default=1.5, gt=0, le=10)
    # Optional YouTube Music location (e.g. "ES"); empty lets YouTube use the server's IP.
    # The language is always "en": "es" silently breaks filtered search (T03b).
    ytm_location: str = Field(default="", pattern=r"^([A-Z]{2})?$")
    # Threads of the catalog pool; each owns one `YTMusic` (sessions are not shared).
    ytm_threads: int = Field(default=3, ge=1, le=16)
    # Per HTTP request to music.youtube.com.
    ytm_timeout_s: float = Field(default=5.0, gt=0, le=60)
    # Global token bucket for music.youtube.com: one `search3` costs three requests.
    ytm_rate_per_s: float = Field(default=2.0, gt=0)
    ytm_burst: float = Field(default=6.0, ge=1)
    # How long a call may wait for a token before giving up as unavailable.
    ytm_max_wait_s: float = Field(default=3.0, ge=0)
    # Circuit breaker after a 429/403/gated answer: open this long, doubling up to the cap.
    ytm_breaker_base_s: float = Field(default=300.0, gt=0)
    ytm_breaker_max_s: float = Field(default=3600.0, gt=0)
