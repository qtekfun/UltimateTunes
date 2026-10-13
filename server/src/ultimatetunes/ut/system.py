# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`GET /ut/v1/server` (public): name, version and capabilities. Owner: PLAN T05.

The Android Connect screen calls it first to check the URL, so it needs no API key and says
nothing about the library or its users. Capabilities follow the admin's switches
(`UT_EXTERNAL_SEARCH`, `UT_RADIO`) and what is installed (`streamingWhileDownloading`:
a real `PendingStreams`); the app hides what is false.
"""

from fastapi import APIRouter, Request

from ultimatetunes import __version__
from ultimatetunes.library.stream import NotStreamingYet
from ultimatetunes.radio.service import radio_settings
from ultimatetunes.search.service import search_settings
from ultimatetunes.subsonic.envelope import API_VERSION, SERVER_TYPE
from ultimatetunes.subsonic.routes.system import EXTENSIONS

public_router = APIRouter()


@public_router.get("/ut/v1/server")
def get_server_info(request: Request) -> dict[str, object]:
    streams = getattr(request.app.state, "pending_streams", None)
    return {
        "name": SERVER_TYPE,
        "version": __version__,
        "apiVersion": "1",
        "openSubsonic": {"apiVersion": API_VERSION, "extensions": list(EXTENSIONS)},
        "capabilities": {
            "externalSearch": search_settings().external_search,
            "radio": radio_settings().radio,
            "charts": radio_settings().radio and radio_settings().charts,
            "lyrics": True,
            "youtubeMusicImport": True,
            "fileImport": True,
            # True once streaming while downloading (PLAN T16) replaced the library's default.
            "streamingWhileDownloading": streams is not None
            and not isinstance(streams, NotStreamingYet),
        },
    }
