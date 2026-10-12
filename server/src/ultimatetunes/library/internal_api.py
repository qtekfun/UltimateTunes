# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Internal worker API, library side (`/internal/v1/library/tracks`): registration of archived
files and ReplayGain updates (contracts/openapi/internal-worker.yaml). The logic lives in
`register.py`; the worker token is checked before (`internal_api.py`)."""

from typing import Annotated

from fastapi import APIRouter, Path, Request
from pydantic import BaseModel, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response

from ultimatetunes.core.services import services
from ultimatetunes.errors import InvalidParameter
from ultimatetunes.library.register import RegisterBody, Registrar, ReplayGainBody

router = APIRouter()
TrackId = Annotated[str, Path(alias="trackId")]
MAX_ID = 64


async def _body[M: BaseModel](request: Request, model: type[M]) -> M:
    """Validated only after the token check (same 401 for every caller without it)."""
    raw = await request.body()
    try:
        return model.model_validate_json(raw or b"null")
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in e["loc"]) or "body" for e in exc.errors()})
        raise InvalidParameter(f"Invalid: {', '.join(fields)}") from exc


def _registrar(request: Request) -> Registrar:
    svc = services(request)
    return Registrar(svc.db, svc.clock, svc.library, svc.staging)


@router.post("/internal/v1/library/tracks")
async def register_track(request: Request) -> Response:
    body = await _body(request, RegisterBody)
    registered = await run_in_threadpool(_registrar(request).register, body)
    return JSONResponse(registered.to_contract())


@router.put("/internal/v1/library/tracks/{trackId}/replaygain")
async def update_replay_gain(request: Request, track_id: TrackId) -> Response:
    body = await _body(request, ReplayGainBody)
    if len(track_id) > MAX_ID:
        raise InvalidParameter("Invalid: trackId")
    await run_in_threadpool(_registrar(request).replay_gain, track_id, body)
    return Response(status_code=204)
