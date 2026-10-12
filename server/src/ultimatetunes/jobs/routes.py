# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Keep a track and follow its download: `/ut/v1/tracks/{id}/...`. Owner: PLAN T08.

Routes in `router` need an API key (see `ut/__init__.py`). The logic lives in `tracks.py`.
"""

from functools import partial
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, ConfigDict, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response

from ultimatetunes.core.authn import Principal, current_principal
from ultimatetunes.core.services import services
from ultimatetunes.errors import InvalidParameter
from ultimatetunes.ids.virtual import VirtualId, parse_kind
from ultimatetunes.jobs import tracks

router = APIRouter()

TrackId = Annotated[str, Path(alias="id", max_length=80)]
MAX_BODY = 4096


class RequestBody(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    reason: Literal["keep", "prefetch"] = "keep"


async def _reason(request: Request) -> tracks.Reason:
    """The optional JSON body (`RequestTrack`); empty means `keep`."""
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise InvalidParameter("Invalid: body")
    if not raw.strip():
        return "keep"
    try:
        return RequestBody.model_validate_json(raw).reason
    except ValidationError as exc:
        raise InvalidParameter("Invalid: reason") from exc


@router.post("/ut/v1/tracks/{id}/request")
async def request_track(
    request: Request,
    track_id: TrackId,
    principal: Annotated[Principal, Depends(current_principal)],
) -> Response:
    parse_kind(track_id, "song")
    reason = await _reason(request)
    svc = services(request)
    target = await run_in_threadpool(tracks.resolve, svc, track_id)
    record = None
    if isinstance(target, VirtualId):
        # An unknown id is `not_found` before anything is written.
        record = await svc.catalog.track(target.payload)
    queued, found = await run_in_threadpool(
        partial(
            tracks.request_in,
            svc,
            track_id,
            record,
            reason=reason,
            user_id=principal.user_id,
        )
    )
    return JSONResponse(found.to_json(), status_code=202 if queued else 200)


@router.get("/ut/v1/tracks/{id}/status")
async def get_track_status(request: Request, track_id: TrackId) -> Response:
    parse_kind(track_id, "song")
    found = await run_in_threadpool(tracks.status, services(request), track_id)
    return JSONResponse(found.to_json())
