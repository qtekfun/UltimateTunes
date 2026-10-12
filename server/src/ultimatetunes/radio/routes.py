# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`/ut/v1/radio` and `/ut/v1/listen-now`. Owner: PLAN T07.

T02 stubs: each route answers `not_implemented` (501) until the task fills it in. Routes in
`router` need an API key (see `ut/__init__.py`); `public_router` routes do not.
"""

from fastapi import APIRouter
from starlette.responses import Response

from ultimatetunes.errors import FeatureNotImplemented

router = APIRouter()


@router.get("/ut/v1/radio")
def get_radio() -> Response:
    raise FeatureNotImplemented()


@router.get("/ut/v1/listen-now")
def get_listen_now() -> Response:
    raise FeatureNotImplemented()
