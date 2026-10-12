# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every OpenSubsonic route file. Each one is owned by a single stream (.claude/ownership.json)."""

from ultimatetunes.subsonic.router import SubsonicRouter
from ultimatetunes.subsonic.routes import (
    annotation,
    browse,
    lyrics,
    media,
    playlists,
    queue,
    radio,
    search,
    system,
)

ROUTERS: tuple[SubsonicRouter, ...] = (
    system.router,
    browse.router,
    media.router,
    search.router,
    lyrics.router,
    playlists.router,
    annotation.router,
    queue.router,
    radio.router,
)
