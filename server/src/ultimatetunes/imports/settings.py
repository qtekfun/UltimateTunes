# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings of the imports area (`UT_IMPORT_*` env vars). Owner: PLAN T11."""

from pydantic import Field

from ultimatetunes.settings import AreaSettings


class ImportSettings(AreaSettings):
    # Catalog calls of ALL imports together (one shared `RateLimiter` bucket, every api
    # process). The catalog's own limit (2 req/s, burst 6; SPEC §11, T03b) is shared with
    # interactive search: imports take at most this share and leave the rest to search.
    import_catalog_rate_per_s: float = Field(default=0.5, gt=0, le=2)
    import_catalog_burst: float = Field(default=1.0, ge=1)
    # Imports one user may have running at once (`conflict` beyond).
    import_max_active_per_user: int = Field(default=3, ge=1, le=20)
