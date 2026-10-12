# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`/ut/v1/me` and `/ut/v1/keys`. Owner: PLAN T04.

T02 stubs: each route answers `not_implemented` (501) until the task fills it in. Routes in
`router` need an API key (see `ut/__init__.py`); `public_router` routes do not.
"""

from fastapi import APIRouter
from starlette.responses import Response

from ultimatetunes.errors import FeatureNotImplemented

router = APIRouter()
public_router = APIRouter()


@router.get("/ut/v1/me")
def get_me() -> Response:
    raise FeatureNotImplemented()


@router.get("/ut/v1/keys")
def list_keys() -> Response:
    raise FeatureNotImplemented()


@public_router.post("/ut/v1/keys")
def create_key() -> Response:
    raise FeatureNotImplemented()


@router.delete("/ut/v1/keys/{keyId}")
def revoke_key() -> Response:
    raise FeatureNotImplemented()
