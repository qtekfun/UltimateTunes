# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings of the library area (`UT_*` env vars). Owner: PLAN T05.

- `UT_LIBRARY_SCAN_ON_START`: scan `/music` in the background when the api starts (adds and
  updates tracks of new or changed files, never deletes anything).
- `UT_COVER_CACHE_TTL_S` / `UT_COVER_CACHE_MAX_BYTES`: the disk cache of external cover art
  under `/data` (contracts/ids.md: TTL 30 days, 512 MiB, oldest evicted first).
- `UT_COVER_FETCH_TIMEOUT_S`: timeout of one fetch from the YouTube image hosts.
"""

from pydantic import Field

from ultimatetunes.settings import AreaSettings


class LibrarySettings(AreaSettings):
    library_scan_on_start: bool = True
    cover_cache_ttl_s: int = Field(default=30 * 24 * 3600, ge=60)
    cover_cache_max_bytes: int = Field(default=512 * 1024 * 1024, ge=1024 * 1024)
    cover_fetch_timeout_s: float = Field(default=10.0, gt=0, le=60)
