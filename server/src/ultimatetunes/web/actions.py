# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""State changes of the web player: playlists (create, rename, add, remove, move, delete) and
stars. Each one is a CSRF-checked POST (`routes.posted`) that calls the OpenSubsonic handler
as the signed-in user, so ownership and visibility are the library's own rules (only the owner
changes a playlist; another user's private playlist is `not_found`).

Forms answer with the page to show next (`routes.go`): HTMX swaps it into `#content`, a plain
form follows a redirect. A star answers the new button.
"""

from fastapi import APIRouter, Request
from starlette.responses import Response

from ultimatetunes.errors import InvalidParameter
from ultimatetunes.web import backend
from ultimatetunes.web.routes import (
    MAX_NAME,
    ItemId,
    Posted,
    PostedDep,
    WebRoute,
    data,
    go,
    page,
    path_id,
)
from ultimatetunes.web.security import PREFIX

router = APIRouter(route_class=WebRoute)
MAX_ID = 80
_STAR_PARAM = {"song": "id", "album": "albumId", "artist": "artistId"}


def _name(post: Posted) -> str:
    name = post.get("name").strip()
    if not name or len(name) > MAX_NAME:
        raise InvalidParameter(f"The name needs 1 to {MAX_NAME} characters")
    return name


def _index(post: Posted, field: str) -> int:
    try:
        return int(post.get(field))
    except ValueError:
        raise InvalidParameter(f"{field} must be a number") from None


def _back(request: Request, playlist_id: str) -> Response:
    return go(request, f"{PREFIX}/playlist/{path_id(playlist_id)}")


@router.post(PREFIX + "/playlists", include_in_schema=False)
async def create_playlist(request: Request, post: PostedDep) -> Response:
    songs = [post.get("song")] if post.get("song") else []
    created = await data(request, post.listener, "createPlaylist", name=_name(post), songId=songs)
    return _back(request, str(created["playlist"]["id"]))


@router.post(PREFIX + "/playlists/{id}/rename", include_in_schema=False)
async def rename_playlist(request: Request, post: PostedDep, item_id: ItemId) -> Response:
    await data(request, post.listener, "updatePlaylist", playlistId=item_id, name=_name(post))
    return _back(request, item_id)


@router.post(PREFIX + "/playlists/{id}/add", include_in_schema=False)
async def add_to_playlist(request: Request, post: PostedDep, item_id: ItemId) -> Response:
    song = post.get("song")
    if not song:
        raise InvalidParameter("Choose a song")
    await data(request, post.listener, "updatePlaylist", playlistId=item_id, songIdToAdd=song)
    return _back(request, item_id)


@router.post(PREFIX + "/playlists/{id}/remove", include_in_schema=False)
async def remove_from_playlist(request: Request, post: PostedDep, item_id: ItemId) -> Response:
    index = post.get("index")
    await data(
        request, post.listener, "updatePlaylist", playlistId=item_id, songIndexToRemove=index
    )
    return _back(request, item_id)


@router.post(PREFIX + "/playlists/{id}/move", include_in_schema=False)
async def move_in_playlist(request: Request, post: PostedDep, item_id: ItemId) -> Response:
    """Moves the song at `index` to `to`. OpenSubsonic has no move: the playlist is rewritten
    with its songs in the new order (`createPlaylist` with `playlistId`, owner only)."""
    index, to = _index(post, "index"), _index(post, "to")
    found = (await data(request, post.listener, "getPlaylist", id=item_id))["playlist"]
    songs = [str(s["id"]) for s in backend.items(found, "entry")]
    if not (0 <= index < len(songs) and 0 <= to < len(songs)):
        raise InvalidParameter("No song at that position")
    songs.insert(to, songs.pop(index))
    await data(request, post.listener, "createPlaylist", playlistId=item_id, songId=songs)
    return _back(request, item_id)


@router.post(PREFIX + "/playlists/{id}/delete", include_in_schema=False)
async def delete_playlist(request: Request, post: PostedDep, item_id: ItemId) -> Response:
    await data(request, post.listener, "deletePlaylist", id=item_id)
    return go(request, f"{PREFIX}/library/playlists")


@router.post(PREFIX + "/star", include_in_schema=False)
async def star(request: Request, post: PostedDep) -> Response:
    """Stars (`on=1`) or unstars (`on=0`) a song, album or artist; answers the new button."""
    kind, item_id, on = post.get("kind"), post.get("id"), post.get("on") == "1"
    param = _STAR_PARAM.get(kind)
    if param is None or not item_id or len(item_id) > MAX_ID:
        raise InvalidParameter("Invalid star request")
    await data(request, post.listener, "star" if on else "unstar", **{param: item_id})
    context = {"kind": kind, "item_id": item_id, "on": on}
    return page(request, "_star.html", context, listener=post.listener)
