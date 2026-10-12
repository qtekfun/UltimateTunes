# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Internal worker API, library side (`/internal/v1/library/tracks`). Owner: PLAN T05 (library
registration; T09 is the worker-side caller).

T02 stubs: each route answers `not_implemented` (501). The worker token is checked before
(`internal_api.py`).
"""

from fastapi import APIRouter
from starlette.responses import Response

from ultimatetunes.errors import FeatureNotImplemented

router = APIRouter()


@router.post("/internal/v1/library/tracks")
def register_track() -> Response:
    raise FeatureNotImplemented()


@router.put("/internal/v1/library/tracks/{trackId}/replaygain")
def update_replay_gain() -> Response:
    raise FeatureNotImplemented()
