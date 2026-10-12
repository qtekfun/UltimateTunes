# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Radio (RF-06). Owned by PLAN T07.

- `service`: the seed → YouTube Music watch playlist → local-first song list.
- `routes`: `/ut/v1/radio` (and the `/ut/v1/listen-now` stub); `getSimilarSongs2` lives in
  `subsonic/routes/radio.py`. Both render with `search.render`.
- `settings`: the area's `UT_*` settings.
"""
