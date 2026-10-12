# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenSubsonic: Browsing and lists. Owner: PLAN T05.

T02 stubs: every endpoint answers `FeatureNotImplemented` (error 0, HTTP 501) until its task
replaces the body. Keep the endpoint names; the pipeline is `subsonic/router.py`.
"""

from ultimatetunes.errors import FeatureNotImplemented
from ultimatetunes.subsonic.router import Payload, SubsonicRequest, SubsonicRouter

router = SubsonicRouter()


@router.endpoint("getArtists")
def get_artists(req: SubsonicRequest) -> Payload:
    raise FeatureNotImplemented()


@router.endpoint("getArtist")
def get_artist(req: SubsonicRequest) -> Payload:
    raise FeatureNotImplemented()


@router.endpoint("getAlbum")
def get_album(req: SubsonicRequest) -> Payload:
    raise FeatureNotImplemented()


@router.endpoint("getSong")
def get_song(req: SubsonicRequest) -> Payload:
    raise FeatureNotImplemented()


@router.endpoint("getAlbumList2")
def get_album_list2(req: SubsonicRequest) -> Payload:
    raise FeatureNotImplemented()


@router.endpoint("getRandomSongs")
def get_random_songs(req: SubsonicRequest) -> Payload:
    raise FeatureNotImplemented()
