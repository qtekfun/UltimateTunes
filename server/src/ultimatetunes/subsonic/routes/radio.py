# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenSubsonic: `getSimilarSongs2`, the radio of a song. Owner: no PLAN task in
.claude/ownership.json yet (the coordinator assigns it; T07 implements it).

T02 stubs: every endpoint answers `FeatureNotImplemented` (error 0, HTTP 501) until its task
replaces the body. Keep the endpoint names; the pipeline is `subsonic/router.py`.
"""

from ultimatetunes.errors import FeatureNotImplemented
from ultimatetunes.subsonic.router import Payload, SubsonicRequest, SubsonicRouter

router = SubsonicRouter()


@router.endpoint("getSimilarSongs2")
def get_similar_songs2(req: SubsonicRequest) -> Payload:
    raise FeatureNotImplemented()
