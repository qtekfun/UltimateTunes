# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Search and the YouTube Music catalog. Owned by PLAN T06.

T02 ships:
- `catalog`: the `MusicCatalog` protocol, its record types and errors (shape from spike T03b),
  and `build_catalog(settings)`, which T06 points at the ytmusicapi implementation.
- `fake`: `FakeMusicCatalog`, invented data, for tests and the test compose stack.
- `routes`: the `/ut/v1/search` stub (OpenSubsonic `search3` is `subsonic/routes/search.py`).
"""
