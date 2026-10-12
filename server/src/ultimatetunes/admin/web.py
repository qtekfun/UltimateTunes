# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""App hook of the admin panel (`app.AREAS`). Owner: PLAN T15.

Mounts `/admin`, the `AdminGate` middleware (network allowlist, body cap, security
headers), the panel's exception handlers, and the notification sweep, which runs inside the
app's lifespan (wrapped here so `app.py` stays untouched).
"""

import asyncio
import contextlib
import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from ultimatetunes.admin import notify, routes
from ultimatetunes.admin.security import AdminGate, SessionCodec
from ultimatetunes.admin.settings import AdminSettings
from ultimatetunes.auth.service import AuthService
from ultimatetunes.core.forwarded import TRUSTED_NETWORKS_STATE
from ultimatetunes.core.netaddr import LOOPBACK
from ultimatetunes.core.services import Services
from ultimatetunes.health import PROBE_NETWORKS_STATE

log = logging.getLogger(__name__)


def install(
    app: FastAPI,
    services: Services,
    settings: AdminSettings | None = None,
    sender: notify.Sender | None = None,
) -> None:
    settings = settings or AdminSettings()
    secret = settings.admin_session_secret
    if secret is None:
        log.warning(
            "UT_ADMIN_SESSION_SECRET is not set: admin sessions use a random key and end when"
            " the api restarts (and do not work across replicas)"
        )
    key = secret.get_secret_value() if secret else secrets.token_urlsafe(48)
    auth = getattr(app.state, "auth", None)
    if not isinstance(auth, AuthService):
        auth = AuthService.from_services(services)
    sender = sender or notify.Sender(credentials=notify.Credentials.from_settings(settings))
    app.state.admin = routes.AdminState(
        services=services,
        auth=auth,
        codec=SessionCodec(key, services.clock, settings.admin_session_ttl_s),
        settings=settings,
        templates=routes.Templates(),
        sender=sender,
    )
    app.include_router(routes.router)
    for exc_class, handler in routes.handlers().items():
        app.add_exception_handler(exc_class, handler)  # type: ignore[arg-type]
    denied = services.settings.worker_network_list
    app.add_middleware(AdminGate, networks=settings.networks(), denied=denied)
    # The same networks decide which per-user login lockout counter a password check moves
    # (`AuthService.verify_password`): inside them, or outside.
    setattr(app.state, TRUSTED_NETWORKS_STATE, (settings.networks(), denied))
    # Whoever may reach the panel may also read the `/readyz` detail.
    setattr(app.state, PROBE_NETWORKS_STATE, LOOPBACK + settings.networks())
    sweep = notify.NotificationSweep(services.db, services.clock, sender)
    _run_during_lifespan(app, sweep, settings.admin_notify_interval_s)


def _run_during_lifespan(app: FastAPI, sweep: notify.NotificationSweep, interval_s: int) -> None:
    inner = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(target: Any) -> AsyncIterator[Any]:
        async with inner(target) as value:
            task = asyncio.create_task(sweep.run_forever(interval_s))
            try:
                yield value
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    app.router.lifespan_context = lifespan
