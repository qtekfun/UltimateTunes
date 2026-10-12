# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenSubsonic: User playlists. Owner: no PLAN task in .claude/ownership.json yet (the coordinator
assigns it; T05 per contracts/db/README.md).

T02 stubs: every endpoint answers `FeatureNotImplemented` (error 0, HTTP 501) until its task
replaces the body. Keep the endpoint names; the pipeline is `subsonic/router.py`.
"""

from ultimatetunes.errors import FeatureNotImplemented
from ultimatetunes.subsonic.router import Payload, SubsonicRequest, SubsonicRouter

router = SubsonicRouter()


@router.endpoint("getPlaylists")
def get_playlists(req: SubsonicRequest) -> Payload:
    raise FeatureNotImplemented()


@router.endpoint("getPlaylist")
def get_playlist(req: SubsonicRequest) -> Payload:
    raise FeatureNotImplemented()


@router.endpoint("createPlaylist")
def create_playlist(req: SubsonicRequest) -> Payload:
    raise FeatureNotImplemented()


@router.endpoint("updatePlaylist")
def update_playlist(req: SubsonicRequest) -> Payload:
    raise FeatureNotImplemented()


@router.endpoint("deletePlaylist")
def delete_playlist(req: SubsonicRequest) -> Payload:
    raise FeatureNotImplemented()
