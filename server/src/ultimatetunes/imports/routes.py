# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Playlist imports: `/ut/v1/imports`. Owner: PLAN T11.

T02 stubs: each route answers `not_implemented` (501) until the task fills it in. Routes in
`router` need an API key (see `ut/__init__.py`); `public_router` routes do not.
"""

from fastapi import APIRouter
from starlette.responses import Response

from ultimatetunes.errors import FeatureNotImplemented

router = APIRouter()


@router.get("/ut/v1/imports")
def list_imports() -> Response:
    raise FeatureNotImplemented()


@router.post("/ut/v1/imports")
def create_import() -> Response:
    raise FeatureNotImplemented()


@router.get("/ut/v1/imports/{importId}")
def get_import() -> Response:
    raise FeatureNotImplemented()
