# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""App hook of the admin panel (`app.AREAS`). Owner: PLAN T15, which can add its middleware
(sessions, CSRF, network allowlist) here without touching `app.py`."""

from fastapi import FastAPI

from ultimatetunes.admin import routes
from ultimatetunes.core.services import Services


def install(app: FastAPI, services: Services) -> None:
    app.include_router(routes.router)
