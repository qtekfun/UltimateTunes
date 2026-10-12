# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenSubsonic: stars and scrobbles (RF-09). Owner: PLAN T05.

The rules (keep actions, external albums and artists, now playing) are in
`library.annotate`. `getStarred2` lists the caller's favourites, newest first; a starred song
that is not archived yet shows as its external `yt:` song.
"""

from starlette.concurrency import run_in_threadpool

from ultimatetunes.errors import MissingParameter
from ultimatetunes.library.annotate import Annotations
from ultimatetunes.library.params import get_bool
from ultimatetunes.library.render import Obj, album_id3, pending_child
from ultimatetunes.library.repository import LibraryRepository
from ultimatetunes.search import render
from ultimatetunes.subsonic.router import Payload, SubsonicRequest, SubsonicRouter

router = SubsonicRouter()


@router.endpoint("star")
async def star(req: SubsonicRequest) -> Payload:
    await Annotations(req.services, req.user.user_id).star(
        req.get_all("id"), req.get_all("albumId"), req.get_all("artistId")
    )
    return {}


@router.endpoint("unstar")
async def unstar(req: SubsonicRequest) -> Payload:
    annotations = Annotations(req.services, req.user.user_id)
    await run_in_threadpool(
        annotations.unstar, req.get_all("id"), req.get_all("albumId"), req.get_all("artistId")
    )
    return {}


@router.endpoint("getStarred2")
def get_starred2(req: SubsonicRequest) -> Payload:
    user = req.user.user_id
    with req.services.db.read() as conn:
        repo = LibraryRepository(conn)
        artists = repo.starred_artists(user)
        albums = repo.starred_albums(user)
        rows = repo.starred_songs(user)
        ready = repo.songs_by_id(user, [r.id for r in rows if r.status == "ready"])
    songs: list[Obj] = []
    for row in rows:
        song = ready.get(row.id)
        child = render.library_child(song) if song else pending_child(row)
        if child is not None:
            songs.append(child)
    return {
        "starred2": {
            "artist": [render.artist_id3(a) for a in artists],
            "album": [album_id3(a) for a in albums],
            "song": songs,
        }
    }


@router.endpoint("scrobble")
async def scrobble(req: SubsonicRequest) -> Payload:
    ids = req.get_all("id")
    if not ids or any(not i for i in ids):
        raise MissingParameter("Required parameter is missing: id")
    submission = get_bool(req, "submission", default=True)
    await Annotations(req.services, req.user.user_id).scrobble(
        ids, req.get_all("time"), submission=bool(submission), client=req.get("c")
    )
    return {}
