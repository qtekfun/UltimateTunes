# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Radio (RF-06). Owned by PLAN T07.

- `service`: the seed → YouTube Music watch playlist → local-first song list.
- `listen_now`: the caller's library-only shelves (no YouTube Music request).
- `recommendations`: "Recommended for you" from the caller's own plays and favourites, each
  seeded into the radio watch playlist (the no-new-host baseline of `docs/recommendations.md`).
- `routes`: `/ut/v1/radio`, `/ut/v1/listen-now` and `/ut/v1/recommendations`;
  `getSimilarSongs2` lives in `subsonic/routes/radio.py`. All render with `search.render`.
- `settings`: the area's `UT_*` settings.
"""
