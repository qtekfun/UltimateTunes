# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""FastAPI application factory."""

from fastapi import FastAPI

from ultimatetunes import __version__, health
from ultimatetunes.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Builds the api. Stateless: everything shared lives in the database or the interfaces."""
    app = FastAPI(
        title="UltimateTunes",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings or Settings()
    app.include_router(health.router)
    return app
