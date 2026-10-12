# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Listen Now (RF-06, RF-11): the caller's shelves, from the library only (never YouTube Music).

- `recentlyPlayed`: albums of the caller's latest plays (`play_history`, real plays only, not
  "now playing" notifications), most recent first, each album once.
- `recentlyAdded`: albums with at least one archived song, newest first.
- `mostPlayed`: the caller's songs by play count (`user_track_stats`), then latest play.
- `favouriteRadios`: one radio per starred song, latest star first; `seedId` goes to
  `GET /ut/v1/radio?seed=`.

Ids are local-first as in radio: an archived song has its library id; a song that is still
`pending` (or `failed`) keeps its `yt:` id and `libraryState`, rendered from the metadata
stored on its track row. Merged tracks never show (their stars and plays moved). Scrobbles
and stars are written elsewhere (T05); this module only reads them.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from ultimatetunes.db.database import Database
from ultimatetunes.db.repository import Repository
from ultimatetunes.ids.resolve import TrackStatus
from ultimatetunes.ids.virtual import is_browse_id, is_video_id
from ultimatetunes.search import render
from ultimatetunes.search.catalog import AlbumRef, ArtistRef, CatalogTrack
from ultimatetunes.search.library import LibraryAlbum, LibrarySearch
from ultimatetunes.search.service import ExternalSong, Song

MAX_ALBUMS = 20
MAX_SONGS = 20
MAX_RADIOS = 10

type Obj = dict[str, object]


@dataclass(frozen=True)
class _Id:
    id: str


@dataclass(frozen=True)
class _Track:
    id: str
    status: TrackStatus
    title: str
    artist_name: str
    album_name: str | None
    track_number: int | None
    year: int | None
    duration_ms: int | None
    yt_video_id: str | None
    yt_album_browse_id: str | None
    yt_artist_channel_id: str | None


_RECENT_ALBUMS = (
    "SELECT t.album_id AS id FROM play_history h JOIN tracks t ON t.id = h.track_id"
    " WHERE h.user_id = ? AND h.submission = 1 AND t.status = 'ready' AND t.album_id IS NOT NULL"
    " GROUP BY t.album_id ORDER BY MAX(h.played_at) DESC, t.album_id LIMIT ?"
)
_ADDED_ALBUMS = (
    "SELECT al.id FROM albums al WHERE EXISTS"
    " (SELECT 1 FROM tracks t WHERE t.album_id = al.id AND t.status = 'ready')"
    " ORDER BY al.created_at DESC, al.id DESC LIMIT ?"
)
_MOST_PLAYED = (
    "SELECT t.id, t.status, t.title, t.artist_name, t.album_name, t.track_number, t.year,"
    " t.duration_ms, t.yt_video_id, t.yt_album_browse_id, t.yt_artist_channel_id"
    " FROM user_track_stats s JOIN tracks t ON t.id = s.track_id"
    " WHERE s.user_id = ? AND s.play_count > 0 AND t.status IN ('ready', 'pending', 'failed')"
    " ORDER BY s.play_count DESC, s.last_played_at DESC, t.id LIMIT ?"
)
_STARRED = (
    "SELECT t.id, t.status, t.title, t.artist_name, t.album_name, t.track_number, t.year,"
    " t.duration_ms, t.yt_video_id, t.yt_album_browse_id, t.yt_artist_channel_id"
    " FROM starred_tracks s JOIN tracks t ON t.id = s.track_id"
    " WHERE s.user_id = ? AND t.status IN ('ready', 'pending', 'failed')"
    " ORDER BY s.starred_at DESC, t.id LIMIT ?"
)


class ListenNowRepository(Repository):
    def recent_album_ids(self, user_id: str, limit: int) -> list[str]:
        return [r.id for r in self.all(_Id, _RECENT_ALBUMS, (user_id, limit))]

    def added_album_ids(self, limit: int) -> list[str]:
        return [r.id for r in self.all(_Id, _ADDED_ALBUMS, (limit,))]

    def most_played(self, user_id: str, limit: int) -> list[_Track]:
        return self.all(_Track, _MOST_PLAYED, (user_id, limit))

    def starred(self, user_id: str, limit: int) -> list[_Track]:
        return self.all(_Track, _STARRED, (user_id, limit))


def _external(track: _Track) -> ExternalSong | None:
    """A not-archived track as the catalog song it came from (None without a valid video)."""
    if track.yt_video_id is None or not is_video_id(track.yt_video_id):
        return None
    browse = track.yt_album_browse_id
    channel = track.yt_artist_channel_id
    song = CatalogTrack(
        video_id=track.yt_video_id,
        title=track.title,
        artists=(
            ArtistRef(track.artist_name, channel if channel and is_browse_id(channel) else None),
        ),
        album=(
            AlbumRef(track.album_name, browse if browse and is_browse_id(browse) else None)
            if track.album_name
            else None
        ),
        duration_s=None if track.duration_ms is None else round(track.duration_ms / 1000),
        year=track.year,
        track_number=track.track_number,
    )
    return ExternalSong(song, track.status)


def _songs(search: LibrarySearch, user_id: str, tracks: Sequence[_Track]) -> list[Song]:
    ready = [t.id for t in tracks if t.status == "ready"]
    library = {s.id: s for s in search.songs_by_id(user_id, ready)}
    songs: list[Song] = []
    for track in tracks:
        song = library.get(track.id) if track.status == "ready" else _external(track)
        if song is not None:
            songs.append(song)
    return songs


def _albums(search: LibrarySearch, user_id: str, ids: Sequence[str]) -> list[LibraryAlbum]:
    found = {a.id: a for a in search.albums_by_id(user_id, ids)}
    return [found[i] for i in ids if i in found]


def _station(song: Song) -> Obj:
    item = render.track_item(song)
    return {
        "seedId": item["id"],
        "title": f"{item['title']} Radio",
        "subtitle": item["artist"] or None,
        "coverArt": item["coverArt"],
    }


def listen_now(db: Database, user_id: str) -> Obj:
    """The `ListenNow` document of contracts/openapi/ut-v1.yaml for `user_id`."""
    with db.read() as conn:
        repo = ListenNowRepository(conn)
        search = LibrarySearch(conn)
        recent = _albums(search, user_id, repo.recent_album_ids(user_id, MAX_ALBUMS))
        added = _albums(search, user_id, repo.added_album_ids(MAX_ALBUMS))
        most = _songs(search, user_id, repo.most_played(user_id, MAX_SONGS))
        starred = _songs(search, user_id, repo.starred(user_id, MAX_RADIOS))
    return {
        "recentlyPlayed": [render.album_item(a) for a in recent],
        "recentlyAdded": [render.album_item(a) for a in added],
        "mostPlayed": [render.track_item(s) for s in most],
        "favouriteRadios": [_station(s) for s in starred],
    }
