# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenSubsonic: Binary endpoints: cover art, stream and download. Owner: PLAN T05 (library files;
`yt:` ids are delegated to `streaming/`, T16).

T02 stubs: every endpoint answers `FeatureNotImplemented` (error 0, HTTP 501) until its task
replaces the body. All three also answer `HEAD` (`head=True`: same headers, no body). Virtual
ids on `getCoverArt` answer error 70 until SPEC section 11 approves the YouTube image hosts.
Keep the endpoint names; the pipeline is `subsonic/router.py`.
"""

from ultimatetunes.errors import FeatureNotImplemented
from ultimatetunes.subsonic.router import Payload, SubsonicRequest, SubsonicRouter

router = SubsonicRouter()


@router.endpoint("getCoverArt", head=True)
def get_cover_art(req: SubsonicRequest) -> Payload:
    raise FeatureNotImplemented()


@router.endpoint("stream", head=True)
def stream(req: SubsonicRequest) -> Payload:
    raise FeatureNotImplemented()


@router.endpoint("download", head=True)
def download(req: SubsonicRequest) -> Payload:
    raise FeatureNotImplemented()
