# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""App hook of the auth area (`app.AREAS`). Owner: PLAN T04."""

from fastapi import FastAPI

from ultimatetunes.core.services import Services


def install(app: FastAPI, services: Services) -> None:
    """Nothing to install yet (routes, middleware or app state of this area go here)."""
