# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenSubsonic: browsing and lists. Owner: PLAN T05.

Library ids browse the library (`ready` tracks only; albums and artists that have one).
Virtual ids are answered from YouTube Music (cached, contracts/ids.md): `getArtist` of a
`ytartist:` id, `getAlbum` of a `ytalbum:` id and `getSong` of a `yt:` id. In those answers a
video already archived appears as the library song (library id); one still `pending` keeps
its `yt:` id. `getSong` of a `yt:` id with a library track answers that track. Nothing here
materializes anything (browsing is not a "keep" action).

`getAlbumList2` and `getRandomSongs` list the library only. `highest` behaves like `frequent`
(no ratings in v1).
"""

import unicodedata
from collections.abc import Sequence
from typing import cast, get_args

from starlette.concurrency import run_in_threadpool

from ultimatetunes.core.clock import format_ts
from ultimatetunes.errors import InvalidParameter, MissingParameter, NotFound
from ultimatetunes.ids.resolve import albums_for_browse_ids, resolve_track, tracks_for_videos
from ultimatetunes.ids.virtual import VirtualId, artist_id, parse_kind
from ultimatetunes.library.render import Obj, album_id3, pending_child
from ultimatetunes.library.repository import AlbumListType, AlbumRow, LibraryRepository
from ultimatetunes.search import render
from ultimatetunes.search.catalog import CatalogTrack
from ultimatetunes.search.library import LibraryArtist
from ultimatetunes.subsonic.router import Payload, SubsonicRequest, SubsonicRouter

router = SubsonicRouter()

IGNORED_ARTICLES = ("The", "El", "La", "Los", "Las", "Le", "Les")
MAX_LIST = 500
DEFAULT_LIST = 10
ALBUM_LIST_TYPES = frozenset(get_args(AlbumListType))


def _not_found(kind: str) -> NotFound:
    return NotFound(f"{kind} not found")


def _sort_key(name: str) -> str:
    for article in IGNORED_ARTICLES:
        if name.lower().startswith(article.lower() + " "):
            return name[len(article) + 1 :].strip()
    return name


def index_name(artist: LibraryArtist) -> str:
    """The index letter of an artist: its sort name without a leading article, folded."""
    key = artist.sort_name or _sort_key(artist.name)
    folded = unicodedata.normalize("NFKD", key)
    first = next((c for c in folded if not unicodedata.combining(c) and not c.isspace()), "")
    return first.upper() if first.isalpha() else "#"


def _artists_payload(artists: Sequence[LibraryArtist]) -> Obj:
    groups: dict[str, list[LibraryArtist]] = {}
    for artist in artists:
        groups.setdefault(index_name(artist), []).append(artist)
    names = sorted(groups, key=lambda n: (n == "#", n))
    index = [
        {
            "name": name,
            "artist": [
                render.artist_id3(a)
                for a in sorted(
                    groups[name],
                    key=lambda a: ((a.sort_name or _sort_key(a.name)).casefold(), a.id),
                )
            ],
        }
        for name in names
    ]
    return {"ignoredArticles": " ".join(IGNORED_ARTICLES), "index": index}


@router.endpoint("getArtists")
def get_artists(req: SubsonicRequest) -> Payload:
    with req.services.db.read() as conn:
        artists = LibraryRepository(conn).artists(req.user.user_id)
    return {"artists": _artists_payload(artists)}


# ---------------------------------------------------------------------- artist


def _library_artist(req: SubsonicRequest, artist: str) -> Obj:
    with req.services.db.read() as conn:
        repo = LibraryRepository(conn)
        found = repo.artist(req.user.user_id, artist)
        if found is None:
            raise _not_found("Artist")
        albums = repo.artist_albums(req.user.user_id, artist)
    return {**render.artist_id3(found), "album": [album_id3(a) for a in albums]}


def _library_albums(req: SubsonicRequest, browse_ids: Sequence[str]) -> dict[str, AlbumRow]:
    with req.services.db.read() as conn:
        mapped = albums_for_browse_ids(conn, browse_ids)
        rows = LibraryRepository(conn).albums_by_id(req.user.user_id, list(mapped.values()))
    return {browse: rows[album] for browse, album in mapped.items() if album in rows}


async def _external_artist(req: SubsonicRequest, channel: str) -> Obj:
    found = await req.services.catalog.artist(channel)
    library = await run_in_threadpool(_library_albums, req, [a.browse_id for a in found.albums])
    now = format_ts(req.services.clock.now())
    albums = [
        album_id3(library[a.browse_id]) if a.browse_id in library else render.album_id3(a, now)
        for a in found.albums
    ]
    virtual = artist_id(found.ref.channel_id)
    return {
        "id": virtual,
        "name": found.ref.name,
        "coverArt": virtual,
        "albumCount": len(albums),
        "album": albums,
    }


@router.endpoint("getArtist")
async def get_artist(req: SubsonicRequest) -> Payload:
    parsed = parse_kind(req.require("id"), "artist")
    if isinstance(parsed, VirtualId):
        return {"artist": await _external_artist(req, parsed.payload)}
    return {"artist": await run_in_threadpool(_library_artist, req, parsed.value)}


# ---------------------------------------------------------------------- album


def _library_album(req: SubsonicRequest, album: str) -> Obj:
    with req.services.db.read() as conn:
        repo = LibraryRepository(conn)
        found = repo.album(req.user.user_id, album)
        if found is None:
            raise _not_found("Album")
        songs = repo.album_songs(req.user.user_id, album)
    return {**album_id3(found), "song": [render.library_child(s) for s in songs]}


def _songs_of_videos(req: SubsonicRequest, tracks: Sequence[CatalogTrack]) -> list[Obj]:
    """Catalog songs, with archived videos replaced by their library songs."""
    with req.services.db.read() as conn:
        refs = tracks_for_videos(conn, [t.video_id for t in tracks])
        ready = [r.id for r in refs.values() if r.status == "ready"]
        songs = LibraryRepository(conn).songs_by_id(req.user.user_id, ready)
    out: list[Obj] = []
    for track in tracks:
        ref = refs.get(track.video_id)
        song = songs.get(ref.id) if ref is not None else None
        out.append(render.library_child(song) if song else render.external_child(track))
    return out


async def _external_album(req: SubsonicRequest, browse: str) -> Obj:
    found = await req.services.catalog.album(browse)
    songs = await run_in_threadpool(_songs_of_videos, req, found.tracks)
    album = render.album_id3(found.ref, format_ts(req.services.clock.now()))
    album["songCount"] = len(songs)
    album["duration"] = sum(t.duration_s or 0 for t in found.tracks)
    return {**album, "song": songs}


@router.endpoint("getAlbum")
async def get_album(req: SubsonicRequest) -> Payload:
    parsed = parse_kind(req.require("id"), "album")
    if isinstance(parsed, VirtualId):
        return {"album": await _external_album(req, parsed.payload)}
    return {"album": await run_in_threadpool(_library_album, req, parsed.value)}


# ---------------------------------------------------------------------- song


def _library_song(req: SubsonicRequest, raw: str) -> Obj | VirtualId:
    """The `Child` of the library track behind `raw`, or the external id to ask the catalog."""
    user = req.user.user_id
    with req.services.db.read() as conn:
        target = resolve_track(conn, raw)
        if isinstance(target, VirtualId):
            return target
        repo = LibraryRepository(conn)
        song = repo.songs_by_id(user, [target.id]).get(target.id)
        if song is not None:
            return render.library_child(song)
        row = repo.track_rows(user, [target.id]).get(target.id)
    child = pending_child(row) if row is not None else None
    if child is None:
        raise _not_found("Song")
    return child


@router.endpoint("getSong")
async def get_song(req: SubsonicRequest) -> Payload:
    raw = req.require("id")
    parse_kind(raw, "song")
    found = await run_in_threadpool(_library_song, req, raw)
    if isinstance(found, VirtualId):
        return {"song": render.external_child(await req.services.catalog.track(found.payload))}
    return {"song": found}


# ---------------------------------------------------------------------- lists


def bounded_int(req: SubsonicRequest, name: str, default: int, low: int, high: int) -> int:
    value = req.get_int(name, default)
    if value is None or not low <= value <= high:
        raise InvalidParameter(f"{name} must be between {low} and {high}")
    return value


def _year(req: SubsonicRequest, name: str) -> int:
    value = req.get_int(name)
    if value is None:
        raise MissingParameter(f"Required parameter is missing: {name}")
    return value


@router.endpoint("getAlbumList2")
def get_album_list2(req: SubsonicRequest) -> Payload:
    kind = req.require("type")
    if kind not in ALBUM_LIST_TYPES:
        raise InvalidParameter("Unknown album list type")
    size = bounded_int(req, "size", DEFAULT_LIST, 1, MAX_LIST)
    offset = bounded_int(req, "offset", 0, 0, 2**31)
    years = (_year(req, "fromYear"), _year(req, "toYear")) if kind == "byYear" else None
    genre = req.require("genre") if kind == "byGenre" else None
    with req.services.db.read() as conn:
        albums = LibraryRepository(conn).album_list(
            req.user.user_id,
            cast("AlbumListType", kind),
            size=size,
            offset=offset,
            years=years,
            genre=genre,
        )
    return {"albumList2": {"album": [album_id3(a) for a in albums]}}


@router.endpoint("getRandomSongs")
def get_random_songs(req: SubsonicRequest) -> Payload:
    size = bounded_int(req, "size", DEFAULT_LIST, 0, MAX_LIST)
    with req.services.db.read() as conn:
        songs = LibraryRepository(conn).random_songs(
            req.user.user_id,
            size,
            genre=req.get("genre") or None,
            from_year=req.get_int("fromYear"),
            to_year=req.get_int("toYear"),
        )
    return {"randomSongs": {"song": [render.library_child(s) for s in songs]}}
