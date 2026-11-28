# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`/ut/v1/podcasts/progress` and `/continue` (PLAN T44). Included by `routes.py`.

An episode id that names no row, malformed ones included, is listed in `unknown` instead of
failing the batch: one bad entry must not block a client's queue of offline changes.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from ultimatetunes.core.authn import Principal, current_principal
from ultimatetunes.core.services import Services, services
from ultimatetunes.errors import InvalidParameter
from ultimatetunes.podcasts import progress

router = APIRouter()

Caller = Annotated[Principal, Depends(current_principal)]


class _Update(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    episode_id: str = Field(alias="episodeId", min_length=1, max_length=80)
    position_ms: int = Field(alias="positionMs", ge=0, le=86_400_000)
    played: bool
    keep: bool = False  # only read when sent (`model_fields_set`); null is refused
    changed_at: AwareDatetime = Field(alias="changedAt")


class _Batch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    items: list[_Update] = Field(min_length=1, max_length=200)


def _progress_json(row: progress.Progress) -> dict[str, object]:
    return {
        "episodeId": row.episode_id,
        "positionMs": row.position_ms,
        "played": row.played,
        "keep": row.keep_file,
        "changedAt": row.changed_at,
    }


def _episode_json(row: progress.StartedEpisode) -> dict[str, object]:
    return {
        "id": row.id,
        "showId": row.show_id,
        "showTitle": row.show_title,
        "title": row.title,
        "coverArt": f"pe-{row.id}",
        "publishedAt": row.published_at,
        "durationMs": row.duration_ms,
        "addedAt": row.discovered_at,
        "state": row.state,
        "sizeBytes": row.size_bytes,
        "progress": {
            "episodeId": row.id,
            "positionMs": row.position_ms,
            "played": row.played,
            "keep": row.keep_file,
            "changedAt": row.changed_at,
        },
    }


def _report(
    svc: Services, user_id: str, updates: list[progress.ProgressUpdate]
) -> progress.ProgressResult:
    with svc.db.transaction() as conn:
        return progress.report(progress.ProgressRepository(conn), svc.clock, user_id, updates)


@router.put("/progress")
async def put_progress(request: Request, principal: Caller) -> dict[str, object]:
    # Read by hand: FastAPI's body validation cannot be strict and still take ISO times.
    try:
        batch = _Batch.model_validate_json(await request.body())
    except ValidationError as exc:
        fields = sorted({".".join(str(part) for part in e["loc"]) for e in exc.errors()})
        raise InvalidParameter(f"Invalid: {', '.join(fields) or 'body'}") from exc
    updates = [
        progress.ProgressUpdate(
            item.episode_id,
            item.position_ms,
            item.played,
            item.keep if "keep" in item.model_fields_set else None,
            item.changed_at,
        )
        for item in batch.items
    ]
    result = await run_in_threadpool(_report, services(request), principal.user_id, updates)
    return {"items": [_progress_json(row) for row in result.items], "unknown": result.unknown}


@router.get("/progress")
def list_progress(
    request: Request,
    principal: Caller,
    since: AwareDatetime | None = None,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> dict[str, object]:
    svc = services(request)
    with svc.db.read() as conn:
        found = progress.page(
            progress.ProgressRepository(conn),
            svc.clock,
            principal.user_id,
            since=since,
            cursor=cursor,
            limit=limit,
        )
    return {
        "items": [_progress_json(row) for row in found.items],
        "nextCursor": found.next_cursor,
        "syncedAt": found.synced_at,
    }


@router.get("/continue")
def list_in_progress(
    request: Request,
    principal: Caller,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, object]:
    with services(request).db.read() as conn:
        rows = progress.ProgressRepository(conn).started(principal.user_id, limit)
    return {"episodes": [_episode_json(row) for row in rows]}
