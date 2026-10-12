# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""What `player.js` calls (JSON) and the media the page loads, all behind the session cookie.

- `GET /web/api/radio/{id}`: `getSimilarSongs2` (a song or an artist seed).
- `GET /web/api/lyrics/{id}`: `getLyricsBySongId`, as `{synced, lines: [{start, text}]}`.
- `GET /web/api/status/{id}` and `GET /web/api/states?id=...`: the download state of `yt:`
  songs, as `GET /ut/v1/tracks/{id}/status` (one, or up to `MAX_STATES` at once).
- `POST /web/api/request/{id}`: keep (download) a song, as `POST /ut/v1/tracks/{id}/request`
  with the same download gates.
- `POST /web/api/scrobble`: `scrobble` ("now playing", then "played").
- `GET|HEAD /web/stream/{id}` and `/web/cover/{id}`: the OpenSubsonic `stream` (HTTP Range,
  streaming while downloading) and `getCoverArt` handlers.
"""

from functools import partial
from typing import Annotated

from fastapi import APIRouter, Query, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response

from ultimatetunes.core.caller import set_caller
from ultimatetunes.errors import InvalidParameter
from ultimatetunes.ids.virtual import VirtualId, parse_kind
from ultimatetunes.jobs import tracks
from ultimatetunes.web import backend
from ultimatetunes.web.routes import (
    ItemId,
    Listener,
    ListenerDep,
    PostedDep,
    WebRoute,
    data,
    state,
)
from ultimatetunes.web.security import PREFIX

router = APIRouter(route_class=WebRoute)
RADIO_SIZE = 50
MAX_STATES = 60


@router.get(PREFIX + "/api/radio/{id}", include_in_schema=False)
async def radio(request: Request, me: ListenerDep, item_id: ItemId) -> Response:
    found = await data(request, me, "getSimilarSongs2", id=item_id, count=str(RADIO_SIZE))
    songs = [backend.song(s) for s in backend.items(found["similarSongs2"], "song")]
    return JSONResponse({"songs": songs})


@router.get(PREFIX + "/api/lyrics/{id}", include_in_schema=False)
async def lyrics(request: Request, me: ListenerDep, item_id: ItemId) -> Response:
    found = await data(request, me, "getLyricsBySongId", id=item_id)
    structured = backend.items(found["lyricsList"], "structuredLyrics")
    return JSONResponse(backend.lyrics(structured))


@router.get(PREFIX + "/api/status/{id}", include_in_schema=False)
async def track_status(request: Request, me: ListenerDep, item_id: ItemId) -> Response:
    """The first-play state of a song, as `GET /ut/v1/tracks/{id}/status`."""
    parse_kind(item_id, "song")
    found = await run_in_threadpool(tracks.status, state(request).services, item_id)
    return JSONResponse(found.to_json())


@router.get(PREFIX + "/api/states", include_in_schema=False)
async def track_states(
    request: Request,
    me: ListenerDep,
    item_ids: Annotated[list[str], Query(alias="id", max_length=MAX_STATES)],
) -> Response:
    """`{id: {state, progress}}` of the `yt:` songs among `id` (the badges of a page)."""
    for item_id in item_ids:
        if len(item_id) > 80:  # noqa: PLR2004 - the id length of every other route
            raise InvalidParameter("id is too long")
        parse_kind(item_id, "song")
    found = await run_in_threadpool(backend.download_states, state(request).services, item_ids)
    return JSONResponse(found)


@router.post(PREFIX + "/api/request/{id}", include_in_schema=False)
async def request_track(request: Request, post: PostedDep, item_id: ItemId) -> Response:
    """Keeps a song in the library (the app's "Download"), as `POST /ut/v1/tracks/{id}/request`
    with `reason: keep`: the caller's download gates apply."""
    parse_kind(item_id, "song")
    svc = state(request).services
    set_caller(post.listener.user.id)
    target = await run_in_threadpool(tracks.resolve, svc, item_id)
    record = await svc.catalog.track(target.payload) if isinstance(target, VirtualId) else None
    queued, found = await run_in_threadpool(
        partial(
            tracks.request_in, svc, item_id, record, reason="keep", user_id=post.listener.user.id
        )
    )
    return JSONResponse(found.to_json(), status_code=202 if queued else 200)


@router.post(PREFIX + "/api/scrobble", include_in_schema=False)
async def scrobble(request: Request, post: PostedDep) -> Response:
    """`submission=false` when a song starts ("now playing"), `true` once it counts as played."""
    item_id = post.get("id")
    submission = "false" if post.get("submission") == "false" else "true"
    await data(request, post.listener, "scrobble", id=item_id, submission=submission)
    return Response(status_code=204)


async def _media(request: Request, me: Listener, name: str, item_id: str) -> Response:
    response = await state(request).backend.media(request, me.principal, name, {"id": item_id})
    if request.method != "HEAD":
        return response
    head = Response(status_code=response.status_code)
    head.raw_headers = list(response.raw_headers)
    return head


@router.api_route(PREFIX + "/stream/{id}", methods=["GET", "HEAD"], include_in_schema=False)
async def stream(request: Request, me: ListenerDep, item_id: ItemId) -> Response:
    return await _media(request, me, "stream", item_id)


@router.api_route(PREFIX + "/cover/{id}", methods=["GET", "HEAD"], include_in_schema=False)
async def cover(request: Request, me: ListenerDep, item_id: ItemId) -> Response:
    return await _media(request, me, "getCoverArt", item_id)
