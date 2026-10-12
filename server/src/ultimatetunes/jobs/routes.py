# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Keep a track and follow its download: `/ut/v1/tracks/{id}/...`. Owner: PLAN T08.

T02 stubs: each route answers `not_implemented` (501) until the task fills it in. Routes in
`router` need an API key (see `ut/__init__.py`); `public_router` routes do not.
"""

from fastapi import APIRouter
from starlette.responses import Response

from ultimatetunes.errors import FeatureNotImplemented

router = APIRouter()


@router.post("/ut/v1/tracks/{id}/request")
def request_track() -> Response:
    raise FeatureNotImplemented()


@router.get("/ut/v1/tracks/{id}/status")
def get_track_status() -> Response:
    raise FeatureNotImplemented()
