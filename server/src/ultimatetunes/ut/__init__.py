# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The `/ut/v1` API (contracts/openapi/ut-v1.yaml): assembly and authentication.

Each stream owns the routes of its area in its own package and exposes `router` (needs an API
key: the dependency below runs `Services.authenticator.authenticate_api_key` first) and,
where the contract allows anonymous calls, `public_router`:

| Module | Paths | Owner |
| --- | --- | --- |
| `ut/system.py` | `GET /ut/v1/server` | unassigned (coordinator) |
| `auth/routes.py` | `/ut/v1/me`, `/ut/v1/keys` | T04 |
| `jobs/routes.py` | `/ut/v1/tracks/{id}/request`, `/status` | T08 |
| `search/routes.py` | `/ut/v1/search` | T06 |
| `radio/routes.py` | `/ut/v1/radio`, `/ut/v1/listen-now` | T07 |
| `imports/routes.py` | `/ut/v1/imports` | T11 |

Errors are `TunesError`s rendered as problems by the app's exception handler.
"""

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from ultimatetunes.auth import routes as auth_routes
from ultimatetunes.core.authn import Principal
from ultimatetunes.core.services import services
from ultimatetunes.imports import routes as import_routes
from ultimatetunes.jobs import routes as job_routes
from ultimatetunes.radio import routes as radio_routes
from ultimatetunes.search import routes as search_routes
from ultimatetunes.ut import system


async def current_principal(request: Request) -> Principal:
    """The caller of an authenticated `/ut/v1` route (cached per request by FastAPI)."""
    principal: Principal = await run_in_threadpool(
        services(request).authenticator.authenticate_api_key,
        request.headers.get("x-api-key"),
        request.query_params.get("apiKey"),
        request.client.host if request.client else None,
    )
    return principal


def build_ut_router() -> APIRouter:
    api = APIRouter()
    for public in (system.public_router, auth_routes.public_router):
        api.include_router(public)
    authenticated = APIRouter(dependencies=[Depends(current_principal)])
    for module in (auth_routes, job_routes, search_routes, radio_routes, import_routes):
        authenticated.include_router(module.router)
    api.include_router(authenticated)
    return api
