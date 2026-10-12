# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`/ut/v1/search` (library merged with YouTube Music). Owner: PLAN T06.

T02 stubs: each route answers `not_implemented` (501) until the task fills it in. Routes in
`router` need an API key (see `ut/__init__.py`); `public_router` routes do not.
"""

from fastapi import APIRouter
from starlette.responses import Response

from ultimatetunes.errors import FeatureNotImplemented

router = APIRouter()


@router.get("/ut/v1/search")
def search() -> Response:
    raise FeatureNotImplemented()
