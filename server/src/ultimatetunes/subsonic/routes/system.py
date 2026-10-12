# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenSubsonic: system endpoints. Owner: PLAN T05.

`getOpenSubsonicExtensions` is public (the OpenSubsonic spec requires it); the others need
credentials. `tokenInfo` answers only to `apiKey` authentication (error 44 otherwise, as for a
key the server cannot identify). There is one music folder, id `1` (contracts/ids.md).
"""

from ultimatetunes.errors import InvalidApiKey
from ultimatetunes.subsonic.router import Payload, SubsonicRequest, SubsonicRouter

router = SubsonicRouter()

# Declared extensions (SPEC RF-02), each at version 1.
EXTENSIONS = ("apiKeyAuthentication", "formPost", "songLyrics")
MUSIC_FOLDER_ID = 1
MUSIC_FOLDER_NAME = "Music"


@router.endpoint("ping")
def ping(req: SubsonicRequest) -> Payload:
    return {}


@router.endpoint("getLicense")
def get_license(req: SubsonicRequest) -> Payload:
    return {"license": {"valid": True}}


@router.endpoint("getOpenSubsonicExtensions", public=True)
def get_open_subsonic_extensions(req: SubsonicRequest) -> Payload:
    return {"openSubsonicExtensions": [{"name": name, "versions": [1]} for name in EXTENSIONS]}


@router.endpoint("tokenInfo")
def token_info(req: SubsonicRequest) -> Payload:
    if not req.get("apiKey"):
        raise InvalidApiKey("tokenInfo needs apiKey authentication")
    return {"tokenInfo": {"username": req.user.username}}


@router.endpoint("getMusicFolders")
def get_music_folders(req: SubsonicRequest) -> Payload:
    return {"musicFolders": {"musicFolder": [{"id": MUSIC_FOLDER_ID, "name": MUSIC_FOLDER_NAME}]}}
