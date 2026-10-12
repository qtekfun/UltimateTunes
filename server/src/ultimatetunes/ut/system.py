# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`GET /ut/v1/server` (public): name, version and capabilities. Owner: PLAN T05.

The Android Connect screen calls it first to check the URL, so it needs no API key and says
nothing about the library or its users. Capabilities follow the admin's switches
(`UT_EXTERNAL_SEARCH`, `UT_RADIO`); the app hides what is false.
"""

from fastapi import APIRouter

from ultimatetunes import __version__
from ultimatetunes.radio.service import radio_settings
from ultimatetunes.search.service import search_settings
from ultimatetunes.subsonic.envelope import API_VERSION, SERVER_TYPE
from ultimatetunes.subsonic.routes.system import EXTENSIONS

public_router = APIRouter()


@public_router.get("/ut/v1/server")
def get_server_info() -> dict[str, object]:
    return {
        "name": SERVER_TYPE,
        "version": __version__,
        "apiVersion": "1",
        "openSubsonic": {"apiVersion": API_VERSION, "extensions": list(EXTENSIONS)},
        "capabilities": {
            "externalSearch": search_settings().external_search,
            "radio": radio_settings().radio,
            "lyrics": True,
            "youtubeMusicImport": True,
            "fileImport": True,
            "streamingWhileDownloading": True,
        },
    }
