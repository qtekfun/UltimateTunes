# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Internal worker API, jobs and worker status (`/internal/v1/jobs`, `/internal/v1/workers`). Owner:
PLAN T08.

T02 stubs: each route answers `not_implemented` (501). The worker token is checked before
(`internal_api.py`).
"""

from fastapi import APIRouter
from starlette.responses import Response

from ultimatetunes.errors import FeatureNotImplemented

router = APIRouter()


@router.post("/internal/v1/jobs/claim")
def claim_job() -> Response:
    raise FeatureNotImplemented()


@router.post("/internal/v1/jobs/{jobId}/heartbeat")
def heartbeat() -> Response:
    raise FeatureNotImplemented()


@router.post("/internal/v1/jobs/{jobId}/progress")
def report_progress() -> Response:
    raise FeatureNotImplemented()


@router.post("/internal/v1/jobs/{jobId}/complete")
def complete_job() -> Response:
    raise FeatureNotImplemented()


@router.post("/internal/v1/jobs/{jobId}/fail")
def fail_job() -> Response:
    raise FeatureNotImplemented()


@router.put("/internal/v1/workers/{workerId}/status")
def report_worker_status() -> Response:
    raise FeatureNotImplemented()
