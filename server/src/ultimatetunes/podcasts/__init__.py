# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Podcasts (docs/podcasts.md, PLAN Wave 5). Separate from the music: episodes are not tracks.

T41 ships the catalog records and `FakePodcastCatalog`, and stubs of `/ut/v1/podcasts`
(`routes.py`), of the OpenSubsonic endpoints (`subsonic/routes/podcasts.py`) and of
`registerEpisode` (`internal_api.py`). T42 to T44 implement them.
"""
