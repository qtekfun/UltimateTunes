# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings of the imports area (`UT_IMPORT_*` env vars). Owner: PLAN T11."""

from pydantic import Field

from ultimatetunes.settings import AreaSettings


class ImportSettings(AreaSettings):
    # Pause after each YouTube Music search of an import. The catalog's own limit (2 req/s,
    # SPEC §11, T03b) is shared with interactive search; pacing imports keeps room for it.
    import_search_interval_s: float = Field(default=1.0, ge=0, le=10)
    # Imports one user may have running at once (`conflict` beyond).
    import_max_active_per_user: int = Field(default=3, ge=1, le=20)
