# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""App hook of the auth area (`app.AREAS`). Owner: PLAN T04.

Puts the `AuthService` in `app.state.auth` for the `/ut/v1/keys` routes and the admin panel, and
creates the first admin from `UT_BOOTSTRAP_ADMIN_USERNAME` + `UT_BOOTSTRAP_ADMIN_PASSWORD`
when both are set and there is no user yet. The password may be the Docker secret file
`/run/secrets/ut_bootstrap_admin_password` instead of an env var (`AreaSettings`); once the
admin exists every start warns until it is removed.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from typing import Any

import anyio
from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool
from starlette.requests import HTTPConnection

from ultimatetunes.auth.service import AuthService
from ultimatetunes.auth.settings import AuthSettings
from ultimatetunes.core.services import Services

log = logging.getLogger(__name__)


def install(app: FastAPI, services: Services) -> None:
    service = (
        services.authenticator
        if isinstance(services.authenticator, AuthService)
        else AuthService.from_services(services)
    )
    app.state.auth = service
    bootstrap_from_env(service, AuthSettings())
    app.router.lifespan_context = with_key_purge(app.router.lifespan_context, service)


PURGE_INTERVAL_S = 24 * 3600
Lifespan = Callable[[Any], AbstractAsyncContextManager[Any]]


async def purge_forever(service: AuthService, interval_s: float = PURGE_INTERVAL_S) -> None:
    """Deletes the old revoked keys at start and then every `interval_s`."""
    while True:
        try:
            await run_in_threadpool(service.purge_revoked_keys)
        except Exception:
            log.exception("purge of revoked api keys failed")
        await anyio.sleep(interval_s)


def with_key_purge(inner: Lifespan, service: AuthService) -> Lifespan:
    @asynccontextmanager
    async def lifespan(app: Any) -> AsyncIterator[Any]:
        async with inner(app) as state:
            task = asyncio.ensure_future(purge_forever(service))
            try:
                yield state
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    return lifespan


def bootstrap_from_env(service: AuthService, settings: AuthSettings) -> bool:
    """True when this call created the first admin."""
    username, password = settings.bootstrap_admin_username, settings.bootstrap_admin_password
    if not username or password is None:
        return False
    created = service.bootstrap_admin(username, password.get_secret_value())
    if created:
        log.info("bootstrap admin %s created from the environment", username)
    else:
        # Audit L5: the first admin exists, so the password only lingers in the environment
        # (`docker inspect`, process listings) or a secret file. It is never used again.
        log.warning(
            "UT_BOOTSTRAP_ADMIN_PASSWORD is still set but users exist: remove the variable"
            " (or the bootstrap_admin_password secret) from the deployment"
        )
    return created


def auth_service(conn: HTTPConnection) -> AuthService:
    """The app's `AuthService` (usable as a FastAPI dependency)."""
    found: AuthService = conn.app.state.auth
    return found
