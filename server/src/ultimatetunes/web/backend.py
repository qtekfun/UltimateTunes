# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the web player reads and changes, through the OpenSubsonic handlers themselves.

The web player is one more client of the server: every page and action calls the handler of
the matching OpenSubsonic endpoint (`subsonic/routes/`) in-process, as the signed-in user, so
the same rules apply as for the app and any other client: visibility and ownership of
playlists, stars, "keep" actions, the per-user search bucket and catalog budget, the download
gates and the listener caps of streaming while downloading. Nothing here touches the database.

The OpenSubsonic answers (`Child`, `AlbumID3`, `ArtistID3`, ...) become the small dicts the
templates and `player.js` use (`song`, `album`, `artist`).
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from inspect import iscoroutinefunction
from typing import Any, cast

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import Response

from ultimatetunes.core.authn import Principal
from ultimatetunes.core.caller import set_caller
from ultimatetunes.core.services import Services
from ultimatetunes.jobs import tracks
from ultimatetunes.subsonic.router import Handler, HandlerResult, SubsonicRequest
from ultimatetunes.subsonic.routes import ROUTERS

type View = dict[str, object]
Params = Mapping[str, str | Sequence[str]]


def endpoints() -> dict[str, Handler]:
    return {name: ep.handler for r in ROUTERS for name, ep in r.endpoints.items()}


class Backend:
    """Calls OpenSubsonic handlers as `principal`."""

    def __init__(self, services: Services, handlers: Mapping[str, Handler]) -> None:
        self._services = services
        self._handlers = handlers

    async def call(
        self, request: Request, principal: Principal, name: str, params: Params
    ) -> HandlerResult:
        # Catalog lookups of this call are charged to the user, as on `/rest` (core/caller.py).
        set_caller(principal.user_id)
        values = {k: [v] if isinstance(v, str) else list(v) for k, v in params.items()}
        ctx = SubsonicRequest(request, values, "json", self._services, principal)
        handler = self._handlers[name]
        if iscoroutinefunction(handler):
            run = cast("Callable[[SubsonicRequest], Awaitable[HandlerResult]]", handler)
            return await run(ctx)
        return cast("HandlerResult", await run_in_threadpool(handler, ctx))

    async def data(
        self, request: Request, principal: Principal, name: str, params: Params
    ) -> dict[str, Any]:
        result = await self.call(request, principal, name, params)
        if isinstance(result, Response):  # pragma: no cover - only binary endpoints answer one
            raise TypeError(f"{name} is a binary endpoint")
        return dict(result)

    async def media(
        self, request: Request, principal: Principal, name: str, params: Params
    ) -> Response:
        result = await self.call(request, principal, name, params)
        if not isinstance(result, Response):  # pragma: no cover - binary endpoints only
            raise TypeError(f"{name} is not a binary endpoint")
        return result


# ---------------------------------------------------------------------- views


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _opt(value: object) -> str | None:
    return None if value in (None, "") else str(value)


def _int(value: object) -> int:
    return value if isinstance(value, int) else 0


def is_external(item_id: str) -> bool:
    return item_id.startswith("yt")


def song(child: Mapping[str, Any]) -> View:
    item_id = _text(child.get("id"))
    return {
        "id": item_id,
        "title": _text(child.get("title")),
        "artist": _text(child.get("displayArtist") or child.get("artist")),
        "artistId": _opt(child.get("artistId")),
        "album": _opt(child.get("album")),
        "albumId": _opt(child.get("albumId")),
        "cover": _opt(child.get("coverArt")),
        "duration": _int(child.get("duration")),
        "starred": bool(child.get("starred")),
        "external": is_external(item_id),
        "state": None,
    }


def album(item: Mapping[str, Any]) -> View:
    item_id = _text(item.get("id"))
    return {
        "id": item_id,
        "name": _text(item.get("name")),
        "artist": _text(item.get("displayArtist") or item.get("artist")),
        "artistId": _opt(item.get("artistId")),
        "cover": _opt(item.get("coverArt")),
        "year": item.get("year") if isinstance(item.get("year"), int) else None,
        "songCount": _int(item.get("songCount")),
        "duration": _int(item.get("duration")),
        "starred": bool(item.get("starred")),
        "external": is_external(item_id),
    }


def artist(item: Mapping[str, Any]) -> View:
    item_id = _text(item.get("id"))
    return {
        "id": item_id,
        "name": _text(item.get("name")),
        "cover": _opt(item.get("coverArt")),
        "albumCount": _int(item.get("albumCount")),
        "starred": bool(item.get("starred")),
        "external": is_external(item_id),
    }


def playlist(item: Mapping[str, Any]) -> View:
    return {
        "id": _text(item.get("id")),
        "name": _text(item.get("name")),
        "owner": _text(item.get("owner")),
        "cover": _opt(item.get("coverArt")),
        "songCount": _int(item.get("songCount")),
        "duration": _int(item.get("duration")),
        "readonly": bool(item.get("readonly")),
    }


def items(parent: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    found = parent.get(key)
    return [x for x in found if isinstance(x, Mapping)] if isinstance(found, list) else []


def lyrics(structured: Sequence[Mapping[str, Any]]) -> View:
    """The lyrics `player.js` shows: the first synced set, else the first plain one."""
    chosen = next((s for s in structured if s.get("synced")), None) or next(iter(structured), None)
    if chosen is None:
        return {"synced": False, "lines": []}
    synced = bool(chosen.get("synced"))
    lines = [
        {
            "start": line.get("start") if synced and isinstance(line.get("start"), int) else None,
            "text": _text(line.get("value")),
        }
        for line in items(chosen, "line")
    ]
    return {"synced": synced, "lines": lines}


def track(item: Mapping[str, Any]) -> View:
    """A song of `/ut/v1` (`TrackItem`, from Listen Now) as the song view."""
    item_id = _text(item.get("id"))
    external = bool(item.get("isExternal"))
    return {
        "id": item_id,
        "title": _text(item.get("title")),
        "artist": _text(item.get("artist")),
        "artistId": _opt(item.get("artistId")),
        "album": _opt(item.get("album")),
        "albumId": _opt(item.get("albumId")),
        "cover": _opt(item.get("coverArt")),
        "duration": _int(item.get("durationSec")),
        "starred": False,
        "external": external,
        "state": _opt(item.get("libraryState")) if external else None,
    }


def station(item: Mapping[str, Any]) -> View:
    """A favourite radio of Listen Now (`seedId`, `title`, `subtitle`, `coverArt`)."""
    return {
        "seed": _text(item.get("seedId")),
        "title": _text(item.get("title")),
        "subtitle": _text(item.get("subtitle")),
        "cover": _opt(item.get("coverArt")),
    }


def download_states(services: Services, ids: Sequence[str]) -> dict[str, View]:
    """The download state of each `yt:` song among `ids` (`GET /ut/v1/tracks/{id}/status`)."""
    found: dict[str, View] = {}
    for item_id in dict.fromkeys(ids):
        if not item_id.startswith("yt:"):
            continue
        status = tracks.status(services, item_id)
        found[item_id] = {"state": status.state, "progress": status.progress}
    return found
