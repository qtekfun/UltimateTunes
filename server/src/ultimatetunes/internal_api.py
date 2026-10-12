# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The internal worker API under `/internal/v1` (contracts/openapi/internal-worker.yaml).

Every route needs `Authorization: Bearer <UT_WORKER_TOKEN>`, compared in constant time. With no
token configured, every call is refused with the same generic problem as a wrong token (no hint
about the configuration): the worker API is never open. It is served only on the internal
listener (`UT_INTERNAL_PORT`, `listeners.py`), reachable over the internal Docker network; the
client port answers 404 for it. Routes live with their owners: `jobs/internal_api.py` (T08:
jobs and worker status) and `library/internal_api.py` (registration of archived files and
ReplayGain updates).
"""

import hmac

from fastapi import APIRouter, Depends, Request

from ultimatetunes.core.services import services
from ultimatetunes.errors import InvalidWorkerToken
from ultimatetunes.jobs import internal_api as job_api
from ultimatetunes.library import internal_api as library_api


def require_worker_token(request: Request) -> None:
    expected = services(request).settings.worker_token
    if expected is None or not expected.get_secret_value():
        raise InvalidWorkerToken()
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        token.strip().encode(), expected.get_secret_value().encode()
    ):
        raise InvalidWorkerToken()


def build_internal_router() -> APIRouter:
    api = APIRouter(dependencies=[Depends(require_worker_token)])
    api.include_router(job_api.router)
    api.include_router(library_api.router)
    return api
