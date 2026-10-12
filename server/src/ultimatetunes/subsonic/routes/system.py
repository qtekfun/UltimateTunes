# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenSubsonic: System endpoints. Owner: PLAN T05.

T02 stubs: every endpoint answers `FeatureNotImplemented` (error 0, HTTP 501) until its task
replaces the body. Keep the endpoint names; the pipeline is `subsonic/router.py`.
"""

from ultimatetunes.errors import FeatureNotImplemented
from ultimatetunes.subsonic.router import Payload, SubsonicRequest, SubsonicRouter

router = SubsonicRouter()


@router.endpoint("ping")
def ping(req: SubsonicRequest) -> Payload:
    raise FeatureNotImplemented()


@router.endpoint("getLicense")
def get_license(req: SubsonicRequest) -> Payload:
    raise FeatureNotImplemented()


@router.endpoint("getOpenSubsonicExtensions", public=True)
def get_open_subsonic_extensions(req: SubsonicRequest) -> Payload:
    raise FeatureNotImplemented()


@router.endpoint("tokenInfo")
def token_info(req: SubsonicRequest) -> Payload:
    raise FeatureNotImplemented()


@router.endpoint("getMusicFolders")
def get_music_folders(req: SubsonicRequest) -> Payload:
    raise FeatureNotImplemented()
