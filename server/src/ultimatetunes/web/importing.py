# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Playlist imports in the web player (RF-08), as in the app: a YouTube Music / YouTube
playlist URL, or a playlist file (CSV, Exportify CSV, Spotify JSON).

The handlers of `/ut/v1/imports` (`imports/routes.py`) do the work with the signed-in user as
caller, so the same validation (URL allowlist, file formats and size), per-user cap of running
imports, ownership (a user sees only their own imports) and background runner apply:
- a URL form is turned into the JSON body `POST /ut/v1/imports` takes;
- a file is posted as `multipart/form-data` straight through (HTMX sends the CSRF token as the
  `X-CSRF-Token` header; the body cap of `/web/imports/file` is the one of the API).
The pages refresh themselves while an import runs.
"""

import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response
from starlette.types import Message

from ultimatetunes.admin.security import csrf_ok
from ultimatetunes.imports import routes as imports
from ultimatetunes.imports.files import FILE_FORMATS
from ultimatetunes.web.routes import (
    CsrfRejected,
    ListenerDep,
    PostedDep,
    WebRoute,
    go,
    page,
    path_id,
)
from ultimatetunes.web.security import PREFIX, UPLOAD_PATH

router = APIRouter(route_class=WebRoute)
IMPORTS = PREFIX + "/imports"
ACTIVE = ("queued", "reading", "matching")
STATE_LABELS = {
    "queued": "Waiting to start",
    "reading": "Reading the playlist",
    "matching": "Finding the songs",
    "done": "Done",
    "failed": "Failed",
}


def _json_request(request: Request, payload: dict[str, Any]) -> StarletteRequest:
    """The same request, with `payload` as its JSON body (what `POST /ut/v1/imports` reads)."""
    body = json.dumps(payload).encode()
    scope = {
        **request.scope,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
    }
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if sent:  # pragma: no cover - the body is read once
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return StarletteRequest(scope, receive)


@router.get(IMPORTS, include_in_schema=False)
async def imports_page(request: Request, me: ListenerDep) -> Response:
    background = BackgroundTasks()
    found = await imports.list_imports(request, background, me.principal, limit=20, offset=0)
    rows = found["imports"]
    active = isinstance(rows, list) and any(r.get("state") in ACTIVE for r in rows)
    context = {
        "imports": rows,
        "formats": FILE_FORMATS,
        "active": active,
        "state_labels": STATE_LABELS,
    }
    response = page(request, "imports.html", context, listener=me)
    response.background = background
    return response


@router.get(IMPORTS + "/{import_id}", include_in_schema=False)
async def import_page(request: Request, me: ListenerDep, import_id: str) -> Response:
    background = BackgroundTasks()
    found = await imports.get_import(request, background, me.principal, import_id)
    context = {
        "item": found,
        "active": found.get("state") in ACTIVE,
        "state_labels": STATE_LABELS,
    }
    response = page(request, "import.html", context, listener=me)
    response.background = background
    return response


@router.post(IMPORTS + "/url", include_in_schema=False)
async def import_url(request: Request, post: PostedDep) -> Response:
    payload: dict[str, Any] = {"url": post.get("url").strip()}
    if post.get("name").strip():
        payload["name"] = post.get("name").strip()
    background = BackgroundTasks()
    created = await imports.create_import(
        _json_request(request, payload), background, post.listener.principal
    )
    found = json.loads(bytes(created.body))
    response = go(request, f"{IMPORTS}/{path_id(found['id'])}")
    response.background = background
    return response


@router.post(UPLOAD_PATH, include_in_schema=False)
async def import_file(request: Request, me: ListenerDep) -> Response:
    """A playlist file; the CSRF token comes in the `X-CSRF-Token` header (HTMX)."""
    if not csrf_ok(request, me.session.csrf, None):
        raise CsrfRejected
    background = BackgroundTasks()
    created = await imports.create_import(request, background, me.principal)
    found = json.loads(bytes(created.body))
    response = go(request, f"{IMPORTS}/{path_id(found['id'])}")
    response.background = background
    return response
