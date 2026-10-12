# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""FastAPI application factory.

Mounts the probes, the OpenSubsonic API (`/rest`), the own API (`/ut/v1`), the internal worker
API (`/internal/v1`) and the admin panel (`/admin`). `TunesError`s raised by `/ut/v1` and
`/internal/v1` handlers become RFC 9457 problems here (OpenSubsonic renders its own envelope in
`subsonic/router.py`); request validation errors become `invalid_parameter`.

Areas extend the app without editing this file: each module in `AREAS` exposes
`install(app, services)`, called once, in order, after the shared routers are mounted. That is
where an area adds its own routes, middleware or app state (the admin panel mounts `/admin` and
its session middleware there). Middleware added later wraps middleware added earlier. Adding a
module to `AREAS` is a coordinator change.
"""

import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import Response

from ultimatetunes import __version__, health
from ultimatetunes.admin import web as admin_web
from ultimatetunes.auth import web as auth_web
from ultimatetunes.core.services import Services, build_services
from ultimatetunes.errors import InternalError, InvalidParameter, TunesError
from ultimatetunes.internal_api import build_internal_router
from ultimatetunes.jobs import web as jobs_web
from ultimatetunes.library import web as library_web
from ultimatetunes.problem import problem_response
from ultimatetunes.settings import Settings
from ultimatetunes.streaming import web as streaming_web
from ultimatetunes.subsonic.router import build_rest_router
from ultimatetunes.subsonic.routes import ROUTERS
from ultimatetunes.ut import build_ut_router

log = logging.getLogger(__name__)


class AreaHook(Protocol):
    def install(self, app: FastAPI, services: Services) -> None: ...


# Owners: auth T04, library T05, jobs T08, streaming T16, admin T15.
AREAS: tuple[AreaHook, ...] = (auth_web, library_web, jobs_web, streaming_web, admin_web)


def create_app(settings: Settings | None = None, services: Services | None = None) -> FastAPI:
    """Builds the api. Stateless: everything shared lives in the database or the interfaces."""
    settings = settings or (services.settings if services else Settings())
    svc = services or build_services(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        svc.db.close()

    app = FastAPI(
        title="UltimateTunes",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.services = svc
    app.include_router(health.router)
    app.include_router(build_rest_router(ROUTERS))
    app.include_router(build_ut_router())
    app.include_router(build_internal_router())
    for area in AREAS:
        area.install(app, svc)
    app.add_exception_handler(TunesError, _tunes_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unexpected_error)
    return app


async def _tunes_error(request: Request, exc: Exception) -> Response:
    error = exc if isinstance(exc, TunesError) else InternalError()
    return problem_response(error, request.url.path)


async def _validation_error(request: Request, exc: Exception) -> Response:
    problems = exc.errors() if isinstance(exc, RequestValidationError) else []
    fields = sorted({".".join(str(p) for p in e.get("loc", ())) for e in problems})
    return problem_response(InvalidParameter(f"Invalid: {', '.join(fields)}"), request.url.path)


async def _unexpected_error(request: Request, exc: Exception) -> Response:
    correlation = secrets.token_hex(4)
    log.error(
        "unhandled error on %s (correlation id %s)", request.url.path, correlation, exc_info=exc
    )
    return problem_response(InternalError(f"Correlation id {correlation}"), request.url.path)
