# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""App hook of the web player (`app.AREAS`).

Mounts `/` (the player's home page), `/web` and the `WebGate` middleware (security headers,
body cap, on/off switch). The session cookies are signed with the admin panel's key
(`UT_ADMIN_SESSION_SECRET`) under the web player's own salts; without that key, a random one
(sessions end on restart).
"""

import logging
import secrets

from fastapi import FastAPI

from ultimatetunes.admin.settings import AdminSettings
from ultimatetunes.auth.service import AuthService
from ultimatetunes.auth.settings import AuthSettings
from ultimatetunes.core.services import Services
from ultimatetunes.web import account, actions, api, backend, importing, pages, routes
from ultimatetunes.web.security import WebGate, WebSessionCodec
from ultimatetunes.web.settings import WebSettings

log = logging.getLogger(__name__)


def install(
    app: FastAPI,
    services: Services,
    settings: WebSettings | None = None,
    admin_settings: AdminSettings | None = None,
) -> None:
    settings = settings or WebSettings()
    admin_settings = admin_settings or AdminSettings()
    secret = admin_settings.admin_session_secret
    key = secret.get_secret_value() if secret else secrets.token_urlsafe(48)
    auth = getattr(app.state, "auth", None)
    if not isinstance(auth, AuthService):
        auth = AuthService.from_services(services)
    app.state.web = routes.WebState(
        services=services,
        auth=auth,
        codec=WebSessionCodec(key, services.clock, settings.web_session_ttl_s),
        settings=settings,
        auth_settings=AuthSettings(),
        templates=routes.Templates(),
        backend=backend.Backend(services, backend.endpoints()),
    )
    app.include_router(pages.home_router)
    if settings.web_enabled:
        for module in (routes, pages, actions, api, account, importing):
            app.include_router(module.router)
    app.add_middleware(WebGate, enabled=settings.web_enabled)
