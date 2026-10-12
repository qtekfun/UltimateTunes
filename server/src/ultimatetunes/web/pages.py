# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The pages of the web player: Listen Now (also the home page `/`), Radio, Library, Search,
album, artist and playlist pages, and "add to a playlist".

Every page reads through the OpenSubsonic handlers as the signed-in user (`routes.data`), so
it shows exactly what that user may see. `yt:` songs carry their download state
(`backend.download_states`), which `player.js` keeps up to date while a download runs.
"""

from collections.abc import Mapping, Sequence
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse, Response

from ultimatetunes.ids.virtual import parse_kind
from ultimatetunes.radio.listen_now import listen_now as listen_now_shelves
from ultimatetunes.web import backend
from ultimatetunes.web.backend import View
from ultimatetunes.web.routes import (
    ItemId,
    ListenerDep,
    SignInRequired,
    WebRoute,
    current_listener,
    data,
    login_page,
    page,
    state,
)
from ultimatetunes.web.security import HOME, PREFIX

router = APIRouter(route_class=WebRoute)
# `/` is always served (the sign-in form, Listen Now, or the plain page when turned off).
home_router = APIRouter(route_class=WebRoute)

PAGE_SIZE = 60
MAX_OFFSET = 100_000
MAX_QUERY = 200
SEARCH_COUNTS = {"artistCount": "12", "albumCount": "18", "songCount": "40"}


async def with_states(request: Request, songs: Sequence[View]) -> list[View]:
    """`songs` with the download state of their `yt:` ones."""
    ids = [str(s["id"]) for s in songs if s["external"]]
    if not ids:
        return list(songs)
    found = await run_in_threadpool(backend.download_states, state(request).services, ids)
    out: list[View] = []
    for song in songs:
        current = found.get(str(song["id"]))
        out.append({**song, "state": current["state"]} if current else dict(song))
    return out


def _songs(parent: Mapping[str, Any], key: str) -> list[View]:
    return [backend.song(s) for s in backend.items(parent, key)]


def _albums(parent: Mapping[str, Any], key: str = "album") -> list[View]:
    return [backend.album(a) for a in backend.items(parent, key)]


def _artists(parent: Mapping[str, Any], key: str = "artist") -> list[View]:
    return [backend.artist(a) for a in backend.items(parent, key)]


def split(items: Sequence[View]) -> tuple[list[View], list[View]]:
    """(library items, YouTube Music items)."""
    return [i for i in items if not i["external"]], [i for i in items if i["external"]]


# ---------------------------------------------------------------------- Listen Now


@home_router.get(HOME, include_in_schema=False)
async def home(request: Request) -> Response:
    """The home page of the server: Listen Now with a session, else the sign-in form. With
    the web player turned off, a page that only says the server runs."""
    if not state(request).settings.web_enabled:
        return page(request, "landing.html", listener=None)
    try:
        me = await run_in_threadpool(current_listener, request)
    except SignInRequired:
        if request.headers.get("hx-request"):
            return Response(status_code=200, headers={"HX-Redirect": HOME})
        return login_page(request)
    return await listen_now(request, me)


@router.get(PREFIX, include_in_schema=False)
async def listen_now(request: Request, me: ListenerDep) -> Response:
    recent = await data(request, me, "getAlbumList2", type="recent", size="12")
    newest = await data(request, me, "getAlbumList2", type="newest", size="18")
    shelves = await run_in_threadpool(listen_now_shelves, state(request).services.db, me.user.id)
    most = [backend.track(t) for t in backend.items(shelves, "mostPlayed")]
    context = {
        "recent": _albums(recent["albumList2"]),
        "newest": _albums(newest["albumList2"]),
        "most": await with_states(request, most),
        "stations": [backend.station(s) for s in backend.items(shelves, "favouriteRadios")],
    }
    return page(request, "listen.html", context, listener=me)


@router.get(PREFIX + "/", include_in_schema=False)
def slash() -> Response:
    return RedirectResponse(HOME, status_code=308)


@router.get(PREFIX + "/radio", include_in_schema=False)
async def radio_page(request: Request, me: ListenerDep) -> Response:
    """Stations: one per favourite song (as in the app), and the artists of the library."""
    shelves = await run_in_threadpool(listen_now_shelves, state(request).services.db, me.user.id)
    artists = await data(request, me, "getArtists")
    every = [a for group in backend.items(artists["artists"], "index") for a in _artists(group)]
    context = {
        "stations": [backend.station(s) for s in backend.items(shelves, "favouriteRadios")],
        "artists": every[:24],
    }
    return page(request, "radio.html", context, listener=me)


# ---------------------------------------------------------------------- Library


@router.get(PREFIX + "/library", include_in_schema=False)
async def library_albums(
    request: Request,
    me: ListenerDep,
    offset: Annotated[int, Query(ge=0, le=MAX_OFFSET)] = 0,
) -> Response:
    found = await data(
        request,
        me,
        "getAlbumList2",
        type="alphabeticalByName",
        size=str(PAGE_SIZE + 1),
        offset=str(offset),
    )
    albums = _albums(found["albumList2"])
    context = {
        "albums": albums[:PAGE_SIZE],
        "next_offset": offset + PAGE_SIZE if len(albums) > PAGE_SIZE else None,
        "prev_offset": max(offset - PAGE_SIZE, 0) if offset else None,
    }
    return page(request, "library_albums.html", context, listener=me)


@router.get(PREFIX + "/library/artists", include_in_schema=False)
async def library_artists(request: Request, me: ListenerDep) -> Response:
    found = await data(request, me, "getArtists")
    groups = [
        {"name": str(group.get("name", "")), "artists": _artists(group)}
        for group in backend.items(found["artists"], "index")
    ]
    return page(request, "library_artists.html", {"groups": groups}, listener=me)


@router.get(PREFIX + "/library/playlists", include_in_schema=False)
async def library_playlists(request: Request, me: ListenerDep) -> Response:
    found = await data(request, me, "getPlaylists")
    playlists = [backend.playlist(p) for p in backend.items(found["playlists"], "playlist")]
    return page(request, "library_playlists.html", {"playlists": playlists}, listener=me)


@router.get(PREFIX + "/library/favourites", include_in_schema=False)
async def library_favourites(request: Request, me: ListenerDep) -> Response:
    found = (await data(request, me, "getStarred2"))["starred2"]
    context = {
        "artists": _artists(found),
        "albums": _albums(found),
        "songs": await with_states(request, _songs(found, "song")),
    }
    return page(request, "library_favourites.html", context, listener=me)


# ---------------------------------------------------------------------- Search


@router.get(PREFIX + "/search", include_in_schema=False)
async def search(
    request: Request,
    me: ListenerDep,
    q: Annotated[str, Query(max_length=MAX_QUERY)] = "",
) -> Response:
    """Library results first, then YouTube Music's (the per-user search bucket of `search3`
    decides when YouTube Music is asked)."""
    query = q.strip()
    context: dict[str, object] = {"q": query, "found": False}
    if query:
        found = (await data(request, me, "search3", query=query, **SEARCH_COUNTS))["searchResult3"]
        songs = await with_states(request, _songs(found, "song"))
        lib_songs, yt_songs = split(songs)
        lib_albums, yt_albums = split(_albums(found))
        lib_artists, yt_artists = split(_artists(found))
        context.update(
            {
                "lib_songs": lib_songs,
                "lib_albums": lib_albums,
                "lib_artists": lib_artists,
                "yt_songs": yt_songs,
                "yt_albums": yt_albums,
                "yt_artists": yt_artists,
                "found": bool(songs or lib_albums or yt_albums or lib_artists or yt_artists),
            }
        )
    return page(request, "search.html", context, listener=me)


# ---------------------------------------------------------------------- items


@router.get(PREFIX + "/album/{id}", include_in_schema=False)
async def album_page(request: Request, me: ListenerDep, item_id: ItemId) -> Response:
    found = (await data(request, me, "getAlbum", id=item_id))["album"]
    context = {
        "album": backend.album(found),
        "songs": await with_states(request, _songs(found, "song")),
    }
    return page(request, "album.html", context, listener=me)


@router.get(PREFIX + "/artist/{id}", include_in_schema=False)
async def artist_page(request: Request, me: ListenerDep, item_id: ItemId) -> Response:
    found = (await data(request, me, "getArtist", id=item_id))["artist"]
    context = {"artist": backend.artist(found), "albums": _albums(found)}
    return page(request, "artist.html", context, listener=me)


@router.get(PREFIX + "/playlist/{id}", include_in_schema=False)
async def playlist_page(request: Request, me: ListenerDep, item_id: ItemId) -> Response:
    found = (await data(request, me, "getPlaylist", id=item_id))["playlist"]
    context = {
        "playlist": backend.playlist(found),
        "songs": await with_states(request, _songs(found, "entry")),
    }
    return page(request, "playlist.html", context, listener=me)


@router.get(PREFIX + "/add/{id}", include_in_schema=False)
async def add_page(request: Request, me: ListenerDep, item_id: ItemId) -> Response:
    """Add a song to one of the caller's own playlists (or to a new one)."""
    parse_kind(item_id, "song")
    song = (await data(request, me, "getSong", id=item_id))["song"]
    found = await data(request, me, "getPlaylists")
    playlists = [backend.playlist(p) for p in backend.items(found["playlists"], "playlist")]
    context = {"song": backend.song(song), "playlists": [p for p in playlists if not p["readonly"]]}
    return page(request, "add.html", context, listener=me)
