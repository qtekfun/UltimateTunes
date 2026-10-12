# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""App hook of the streaming area (`app.AREAS`). Owner: PLAN T16."""

from fastapi import FastAPI

from ultimatetunes.core.services import Services


def install(app: FastAPI, services: Services) -> None:
    """Nothing to install yet (T16 may add routes, middleware or app state here)."""
