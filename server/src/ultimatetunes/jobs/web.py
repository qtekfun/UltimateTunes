# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""App hook of the jobs area (`app.AREAS`). Owner: PLAN T08.

Keeps the area's settings in the app state; the routes themselves are mounted by
`internal_api.py` (worker API) and `ut/__init__.py` (`/ut/v1/tracks`).
"""

from fastapi import FastAPI

from ultimatetunes.core.services import Services
from ultimatetunes.jobs.settings import JobsSettings


def install(app: FastAPI, services: Services) -> None:
    app.state.jobs_settings = JobsSettings()
