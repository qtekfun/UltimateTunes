# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`/admin` placeholder. Owner: PLAN T15 (sessions, CSRF, network allowlist, admin role).

T02: every path under `/admin` answers 501 with a short HTML page and no data at all.
"""

from fastapi import APIRouter
from starlette.responses import HTMLResponse

router = APIRouter()

_PAGE = (
    "<!doctype html><html lang=en><meta charset=utf-8><title>UltimateTunes admin</title>"
    "<p>The admin panel is not implemented yet.</p></html>"
)


@router.get("/admin")
@router.get("/admin/{rest:path}")
def placeholder() -> HTMLResponse:
    return HTMLResponse(_PAGE, status_code=501, headers={"Cache-Control": "no-store"})
