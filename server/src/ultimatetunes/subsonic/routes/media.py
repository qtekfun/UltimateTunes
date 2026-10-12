# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenSubsonic: Binary endpoints: cover art, stream and download. Owner: PLAN T05 (library files;
`yt:` ids are delegated to `streaming/`, T16).

T02 stubs: every endpoint answers `FeatureNotImplemented` (error 0, HTTP 501) until its task
replaces the body. Keep the endpoint names; the pipeline is `subsonic/router.py`.
"""

from ultimatetunes.errors import FeatureNotImplemented
from ultimatetunes.subsonic.router import Payload, SubsonicRequest, SubsonicRouter

router = SubsonicRouter()


@router.endpoint("getCoverArt")
def get_cover_art(req: SubsonicRequest) -> Payload:
    raise FeatureNotImplemented()


@router.endpoint("stream")
def stream(req: SubsonicRequest) -> Payload:
    raise FeatureNotImplemented()


@router.endpoint("download")
def download(req: SubsonicRequest) -> Payload:
    raise FeatureNotImplemented()
