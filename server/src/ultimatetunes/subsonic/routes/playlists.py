# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenSubsonic: user playlists (RF-09). Owner: PLAN T05.

Visibility, ownership and the "keep" rule for `yt:` songs are in `library.playlists`.
`getPlaylists` accepts only the caller's own `username` (error 50 otherwise).
"""

from starlette.concurrency import run_in_threadpool

from ultimatetunes.errors import Forbidden, InvalidParameter
from ultimatetunes.library.params import get_bool
from ultimatetunes.library.playlists import Playlists
from ultimatetunes.library.songs import check_count
from ultimatetunes.subsonic.router import Payload, SubsonicRequest, SubsonicRouter

router = SubsonicRouter()


def _playlists(req: SubsonicRequest) -> Playlists:
    return Playlists(req.services, req.user.user_id)


@router.endpoint("getPlaylists")
def get_playlists(req: SubsonicRequest) -> Payload:
    username = req.get("username")
    if username and username.lower() != req.user.username:
        raise Forbidden("Only your own playlists can be listed")
    return {"playlists": {"playlist": _playlists(req).visible()}}


@router.endpoint("getPlaylist")
async def get_playlist(req: SubsonicRequest) -> Payload:
    return {"playlist": await _playlists(req).with_songs(req.require("id"))}


@router.endpoint("createPlaylist")
async def create_playlist(req: SubsonicRequest) -> Payload:
    songs = req.get_all("songId")
    check_count(songs)
    playlist = await _playlists(req).create(req.get("name"), req.get("playlistId"), songs)
    return {"playlist": playlist}


def _indexes(req: SubsonicRequest) -> list[int]:
    out: list[int] = []
    for value in req.get_all("songIndexToRemove"):
        try:
            out.append(int(value))
        except ValueError:
            raise InvalidParameter("songIndexToRemove must be an integer") from None
    return out


@router.endpoint("updatePlaylist")
async def update_playlist(req: SubsonicRequest) -> Payload:
    add = req.get_all("songIdToAdd")
    remove = _indexes(req)
    check_count([*add, *map(str, remove)])
    await _playlists(req).update(
        req.require("playlistId"),
        name=req.get("name"),
        comment=req.get("comment"),
        public=get_bool(req, "public"),
        add=add,
        remove=remove,
    )
    return {}


@router.endpoint("deletePlaylist")
async def delete_playlist(req: SubsonicRequest) -> Payload:
    await run_in_threadpool(_playlists(req).delete, req.require("id"))
    return {}
