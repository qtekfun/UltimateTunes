# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Playlist imports: `/ut/v1/imports` (RF-08). Owner: PLAN T11.

Routes in `router` need an API key (see `ut/__init__.py`). `POST` takes a YouTube Music /
YouTube playlist URL as JSON (`CreateImport`) or an uploaded file as multipart
(`CreateFileImport`), validates it at once (`unsupported_url`, `invalid_parameter`,
`payload_too_large`), stores the import and answers `202`; the work runs in the background
(`runner.py`). Each user sees only their own imports. A user may have a few
imports running at once (`UT_IMPORT_MAX_ACTIVE_PER_USER`, `conflict` beyond).
The handlers take the caller from `core.authn.current_principal`, the same dependency the
`/ut/v1` router runs, so FastAPI authenticates once per request.
"""

import json
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from ultimatetunes.core.authn import Principal, current_principal
from ultimatetunes.core.clock import format_ts
from ultimatetunes.core.services import Services, services
from ultimatetunes.errors import Conflict, InvalidParameter, NotFound
from ultimatetunes.ids.uuid7 import new_id
from ultimatetunes.ids.virtual import is_uuid
from ultimatetunes.imports import render
from ultimatetunes.imports.files import SourceItem, parse_file
from ultimatetunes.imports.repository import ImportRepository, ImportSource
from ultimatetunes.imports.runner import ImportRunner
from ultimatetunes.imports.settings import ImportSettings
from ultimatetunes.imports.upload import MAX_JSON_BYTES, read_body, read_file_upload
from ultimatetunes.imports.urls import MAX_URL_LENGTH, playlist_id_from_url


class CreateImport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str = Field(min_length=1, max_length=MAX_URL_LENGTH)
    name: str | None = Field(default=None, max_length=200)


def _resume(svc: Services, background: BackgroundTasks, user_id: str) -> None:
    """Schedules the user's imports whose runner died (see `runner.py`)."""
    runner = ImportRunner.of(svc)
    with svc.db.read() as conn:
        active = ImportRepository(conn).active_ids(user_id)
    for import_id in runner.stale(active):
        background.add_task(runner.run, import_id)


def _detail(svc: Services, import_id: str, user_id: str) -> dict[str, object]:
    with svc.db.read() as conn:
        repo = ImportRepository(conn)
        row = repo.get(import_id, user_id)
        if row is None:
            raise NotFound("No such import")
        items = repo.items(import_id)
        tracks = repo.tracks([i.track_id for i in items if i.track_id])
    return render.full(row, items, tracks)


async def _json_request(request: Request) -> CreateImport:
    body = await read_body(request, MAX_JSON_BYTES)
    try:
        return CreateImport.model_validate(json.loads(body))
    except (ValueError, ValidationError):
        raise InvalidParameter("Expected a JSON object with `url` (and optional `name`)") from None


def _create(  # noqa: PLR0913 - the fields of a new import
    svc: Services,
    user_id: str,
    source: ImportSource,
    *,
    url: str | None = None,
    playlist_id: str | None = None,
    name: str | None = None,
    items: Sequence[SourceItem] = (),
) -> str:
    now = format_ts(svc.clock.now())
    import_id = new_id(svc.clock)
    with svc.db.transaction() as conn:
        repo = ImportRepository(conn)
        cap = ImportSettings().import_max_active_per_user
        if len(repo.active_ids(user_id)) >= cap:
            raise Conflict(f"{cap} imports are already running; wait for one to finish")
        repo.create(
            import_id=import_id,
            user_id=user_id,
            source=source,
            source_url=url,
            source_playlist_id=playlist_id,
            name=name,
            now=now,
        )
        if items:
            repo.add_items(import_id, items, now)
    return import_id


async def _store(request: Request, svc: Services, user_id: str) -> str:
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type == "application/json":
        payload = await _json_request(request)
        playlist_id = playlist_id_from_url(payload.url)
        return await run_in_threadpool(
            lambda: _create(
                svc,
                user_id,
                "ytmusic",
                url=payload.url.strip(),
                playlist_id=playlist_id,
                name=payload.name,
            )
        )
    if content_type == "multipart/form-data":
        upload = await read_file_upload(request)
        parsed = await run_in_threadpool(
            lambda: parse_file(upload.data, upload.fmt, filename=upload.filename, name=upload.name)
        )
        return await run_in_threadpool(
            lambda: _create(
                svc, user_id, upload.fmt, name=upload.name or parsed.name, items=parsed.items
            )
        )
    raise InvalidParameter("Send application/json (a URL) or multipart/form-data (a file)")


router = APIRouter()
Caller = Annotated[Principal, Depends(current_principal)]


@router.get("/ut/v1/imports")
async def list_imports(
    request: Request,
    background: BackgroundTasks,
    principal: Caller,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    svc = services(request)

    def load() -> dict[str, object]:
        _resume(svc, background, principal.user_id)
        with svc.db.read() as conn:
            rows = ImportRepository(conn).list_for(principal.user_id, limit, offset)
        return {"imports": [render.summary(r) for r in rows]}

    return await run_in_threadpool(load)


@router.post("/ut/v1/imports")
async def create_import(
    request: Request, background: BackgroundTasks, principal: Caller
) -> JSONResponse:
    svc = services(request)
    import_id = await _store(request, svc, principal.user_id)
    body = await run_in_threadpool(_detail, svc, import_id, principal.user_id)
    background.add_task(ImportRunner.of(svc).run, import_id)
    return JSONResponse(body, status_code=202, headers={"Location": f"/ut/v1/imports/{import_id}"})


@router.get("/ut/v1/imports/{import_id}")
async def get_import(
    request: Request, background: BackgroundTasks, principal: Caller, import_id: str
) -> dict[str, object]:
    svc = services(request)
    if not is_uuid(import_id):
        raise NotFound("No such import")

    def load() -> dict[str, object]:
        body = _detail(svc, import_id, principal.user_id)
        _resume(svc, background, principal.user_id)
        return body

    return await run_in_threadpool(load)
