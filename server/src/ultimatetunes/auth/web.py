# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""App hook of the auth area (`app.AREAS`). Owner: PLAN T04.

Puts the `AuthService` in `app.state.auth` for the `/ut/v1/keys` routes and the admin panel, and
creates the first admin from `UT_BOOTSTRAP_ADMIN_USERNAME` + `UT_BOOTSTRAP_ADMIN_PASSWORD`
when both are set and there is no user yet.
"""

import logging

from fastapi import FastAPI
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


def bootstrap_from_env(service: AuthService, settings: AuthSettings) -> bool:
    """True when this call created the first admin."""
    username, password = settings.bootstrap_admin_username, settings.bootstrap_admin_password
    if not username or password is None:
        return False
    created = service.bootstrap_admin(username, password.get_secret_value())
    if created:
        log.info("bootstrap admin %s created from the environment", username)
    return created


def auth_service(conn: HTTPConnection) -> AuthService:
    """The app's `AuthService` (usable as a FastAPI dependency)."""
    found: AuthService = conn.app.state.auth
    return found
