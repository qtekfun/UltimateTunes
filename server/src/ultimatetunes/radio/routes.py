# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`/ut/v1/radio`, `/ut/v1/listen-now`, `/ut/v1/recommendations`, `/ut/v1/charts`,
`/ut/v1/moods`. Owner: PLAN T07.

Routes in `router` need an API key (see `ut/__init__.py`). `/ut/v1/radio` answers the seed
first and then the radio, local-first (`radio.service`); `TrackItem` carries no per-user
field, so it does not need the caller's identity. `/ut/v1/listen-now` is the caller's shelves
(`radio.listen_now`), library only. `/ut/v1/recommendations` are new songs seeded from the
caller's own plays and favourites plus, when the admin switched them on, external-source
shelves (`radio.recommendations`, `radio.external`). `/ut/v1/charts` and `/ut/v1/moods` are
YouTube Music's own public charts and mood/genre playlists (`radio.discovery`). All reach
YouTube Music (or, for an external source, its approved host) and are charged to the caller's
bucket like `/ut/v1/radio`; everything is mapped local-first.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from starlette.concurrency import run_in_threadpool

from ultimatetunes.core.authn import Principal, current_principal
from ultimatetunes.core.services import services
from ultimatetunes.radio.discovery import MAX_ITEMS as MAX_DISCOVERY_ITEMS
from ultimatetunes.radio.discovery import ChartsService
from ultimatetunes.radio.listen_now import listen_now
from ultimatetunes.radio.recommendations import MAX_ITEMS, RecommendationsService
from ultimatetunes.radio.service import MAX_RADIO, RadioService
from ultimatetunes.search import render

router = APIRouter()
DEFAULT_LIMIT = 50
DEFAULT_RECOMMENDATION_LIMIT = 20
DEFAULT_DISCOVERY_LIMIT = 50
MAX_MOOD_PARAMS = 128


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
        "shelves": [
            {
                "source": shelf.source,
                "title": shelf.title,
                "items": [render.track_item(s) for s in shelf.items],
            }
            for shelf in recs.shelves
        ],
    }


@router.get("/ut/v1/charts")
async def get_charts(
    request: Request,
    _principal: Annotated[Principal, Depends(current_principal)],
    country: Annotated[str | None, Query(min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_DISCOVERY_ITEMS)] = DEFAULT_DISCOVERY_LIMIT,
) -> dict[str, object]:
    charts = await ChartsService.of(services(request)).charts(_principal.user_id, country, limit)
    return {
        "country": charts.country,
        "items": [render.track_item(s) for s in charts.items],
    }


@router.get("/ut/v1/moods")
async def get_moods(
    request: Request, _principal: Annotated[Principal, Depends(current_principal)]
) -> dict[str, object]:
    moods = await ChartsService.of(services(request)).moods()
    return {"categories": [{"id": m.params, "title": m.title} for m in moods]}


@router.get("/ut/v1/moods/{mood_id}")
async def get_mood(
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
    mood_id: Annotated[str, Path(min_length=1, max_length=MAX_MOOD_PARAMS)],
    limit: Annotated[int, Query(ge=1, le=MAX_DISCOVERY_ITEMS)] = DEFAULT_DISCOVERY_LIMIT,
) -> dict[str, object]:
    svc = ChartsService.of(services(request))
    items = await svc.mood_tracks(principal.user_id, mood_id, limit)
    return {"id": mood_id, "items": [render.track_item(s) for s in items]}
