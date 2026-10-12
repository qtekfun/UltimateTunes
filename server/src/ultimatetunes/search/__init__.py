# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Search and the YouTube Music catalog. Owned by PLAN T06 (SPEC §11, T03b).

- `catalog`: the `MusicCatalog` protocol, its records and errors, and `build_catalog`.
- `ytmusic`: the ytmusicapi implementation (thread pool, one `YTMusic` per thread, our HTTP
  session); `parse`: ytmusicapi responses → records.
- `guard`: cache, single flight, rate limit, retry and circuit breaker around any catalog;
  `codec`: records ↔ cache JSON.
- `fake`: `FakeMusicCatalog`, invented data, for tests and the test compose stack.
- `library`, `service`, `render`: library search, the merge with external results, and the
  wire shapes of `search3` (`subsonic/routes/search.py`) and `/ut/v1/search` (`routes`).
- `text`: name normalisation for matching; `settings`: the area's `UT_*` settings.
"""
