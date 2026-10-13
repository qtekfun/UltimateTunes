# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`/ut/v1/radio`, `/ut/v1/listen-now` and `/ut/v1/recommendations`. Owner: PLAN T07.

Routes in `router` need an API key (see `ut/__init__.py`). `/ut/v1/radio` answers the seed
first and then the radio, local-first (`radio.service`); `TrackItem` carries no per-user
field, so it does not need the caller's identity. `/ut/v1/listen-now` is the caller's shelves
(`radio.listen_now`), library only. `/ut/v1/recommendations` are new songs seeded from the
caller's own plays and favourites (`radio.recommendations`); it reaches YouTube Music through
the same radio watch playlist, charged to the caller's bucket like `/ut/v1/radio`.

`/ut/v1/recommendations` is an **additive** endpoint not yet in `contracts/openapi/ut-v1.yaml`
(contracts are frozen per wave; the proposed schema is in `docs/recommendations.md`, awaiting
the coordinator). Its items are `TrackItem`s, which the contract already defines.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from starlette.concurrency import run_in_threadpool

from ultimatetunes.core.authn import Principal, current_principal
from ultimatetunes.core.services import services
from ultimatetunes.radio.listen_now import listen_now
from ultimatetunes.radio.recommendations import MAX_ITEMS, RecommendationsService
from ultimatetunes.radio.service import MAX_RADIO, RadioService
from ultimatetunes.search import render

router = APIRouter()
DEFAULT_LIMIT = 50
DEFAULT_RECOMMENDATION_LIMIT = 20


@router.get("/ut/v1/radio")
async def get_radio(
    request: Request,
    seed: Annotated[str, Query(min_length=1, max_length=80)],
    limit: Annotated[int, Query(ge=1, le=MAX_RADIO)] = DEFAULT_LIMIT,
) -> dict[str, object]:
    radio = await RadioService.of(services(request)).radio(None, seed, limit)
    return {
        "seed": render.track_item(radio.seed),
        "items": [render.track_item(s) for s in radio.items],
    }


@router.get("/ut/v1/listen-now")
async def get_listen_now(
    request: Request, principal: Annotated[Principal, Depends(current_principal)]
) -> dict[str, object]:
    return await run_in_threadpool(listen_now, services(request).db, principal.user_id)


@router.get("/ut/v1/recommendations")
async def get_recommendations(
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
    limit: Annotated[int, Query(ge=1, le=MAX_ITEMS)] = DEFAULT_RECOMMENDATION_LIMIT,
) -> dict[str, object]:
    recs = await RecommendationsService.of(services(request)).recommend(principal.user_id, limit)
    return {
        "recommendedForYou": [render.track_item(s) for s in recs.recommended_for_you],
        "becauseYouPlayed": [
            {
                "seed": render.track_item(shelf.seed),
                "items": [render.track_item(s) for s in shelf.items],
            }
            for shelf in recs.because_you_played
        ],
    }
