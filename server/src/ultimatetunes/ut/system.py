# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`GET /ut/v1/server` (public). Owner: PLAN T05 (.claude/ownership.json).

T02 stub: answers `not_implemented` (501).
"""

from fastapi import APIRouter
from starlette.responses import Response

from ultimatetunes.errors import FeatureNotImplemented

public_router = APIRouter()


@public_router.get("/ut/v1/server")
def get_server_info() -> Response:
    raise FeatureNotImplemented()
