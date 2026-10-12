# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Radio: the YouTube Music watch playlist of a seed, local-first (RF-06, contracts/ids.md).

Seeds:
- a song: library UUID or `yt:` id. A library track plays the radio of its video
  (`yt_video_id`, else its oldest `yt:` alias); a track that never came from YouTube Music
  (scanned from disk) uses the first catalog song found for "title artist".
- an artist (`getSimilarSongs2` only): `ytartist:` id, or a library artist UUID. The radio
  starts from the artist's first top song on YouTube Music (library artists use their channel
  id; without one, their first song in the library).

Every song of the watch playlist is mapped like search results: a video archived in the
library (`ready`) becomes the library song and its library id; a `pending` or `failed` one
keeps its `yt:` id and carries that state. A song appears once (several videos may alias one
track), and a song seed is never repeated among the items. Nothing is materialized: listing
a radio is not a "keep" action. Catalog failures surface as `TunesError`s (not found,
upstream unavailable); the catalog serves at most `guard.RADIO_SIZE` songs per seed.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, cast

from starlette.concurrency import run_in_threadpool

from ultimatetunes.db.database import Database
from ultimatetunes.db.driver import Connection
from ultimatetunes.errors import FeatureDisabled, InvalidId, NotFound
from ultimatetunes.ids.resolve import TrackRef, resolve_track, tracks_for_videos
from ultimatetunes.ids.virtual import SONG_PREFIX, VirtualId, parse_id, song_id
from ultimatetunes.radio.settings import RadioSettings
from ultimatetunes.search.catalog import CatalogTrack, MusicCatalog
from ultimatetunes.search.library import LibrarySearch, LibrarySong
from ultimatetunes.search.service import ExternalSong, Song

if TYPE_CHECKING:
    from ultimatetunes.core.services import Services

# Largest radio a client can ask for (contracts: `limit`, `count`).
MAX_RADIO = 100


@dataclass(frozen=True)
class Radio:
    """`seed`: the seed song (for an artist seed, its first top song); `items`: the rest."""

    seed: Song
    items: Sequence[Song]
    from_artist: bool = False


@dataclass(frozen=True)
class _Seed:
    video_id: str
    # The library track of the seed song, if it has one.
    ref: TrackRef | None
    from_artist: bool = False


@dataclass(frozen=True)
class _LibraryTrack:
    ref: TrackRef
    video_id: str | None
    # "title artist": the catalog search of a track that has no video.
    query: str
    # Chosen for a library artist seed.
    from_artist: bool = False


@lru_cache(maxsize=1)
def radio_settings() -> RadioSettings:
    return RadioSettings()


def _video_of(conn: Connection, ref: TrackRef, *, from_artist: bool = False) -> _LibraryTrack:
    # `ref` was just read in this same transaction: the row exists.
    row = cast(
        "Mapping[str, object]",
        conn.execute(
            "SELECT title, artist_name, yt_video_id FROM tracks WHERE id = ?", (ref.id,)
        ).fetchone(),
    )
    query = f"{row['title']} {row['artist_name']}"
    if row["yt_video_id"] is not None:
        return _LibraryTrack(ref, str(row["yt_video_id"]), query, from_artist)
    alias = conn.execute(
        "SELECT alias FROM track_aliases WHERE track_id = ? ORDER BY created_at, alias",
        (ref.id,),
    ).fetchone()
    video = str(alias["alias"]).removeprefix(SONG_PREFIX) if alias is not None else None
    return _LibraryTrack(ref, video, query, from_artist)


def _library_artist(conn: Connection, artist_id: str) -> _LibraryTrack | str:
    """A library artist → its channel id, or its first library song."""
    row = conn.execute("SELECT yt_channel_id FROM artists WHERE id = ?", (artist_id,)).fetchone()
    if row is None:
        raise NotFound("Song or artist not found")
    if row["yt_channel_id"] is not None:
        return str(row["yt_channel_id"])
    track = conn.execute(
        "SELECT id FROM tracks WHERE artist_id = ? AND status = 'ready'"
        " ORDER BY title_norm, id LIMIT 1",
        (artist_id,),
    ).fetchone()
    if track is None:
        raise NotFound("This artist has no songs yet")
    return _video_of(conn, TrackRef(str(track["id"]), "ready"), from_artist=True)


def _song(track: CatalogTrack, ref: TrackRef | None, library: dict[str, LibrarySong]) -> Song:
    """The library song when the track is archived (`library` holds only `ready` songs)."""
    song = library.get(ref.id) if ref is not None else None
    if song is not None:
        return song
    return ExternalSong(track, ref.status if ref is not None else None)


class RadioService:
    def __init__(self, db: Database, catalog: MusicCatalog, settings: RadioSettings) -> None:
        self._db = db
        self._catalog = catalog
        self._settings = settings

    @classmethod
    def of(cls, services: "Services") -> "RadioService":
        return cls(services.db, services.catalog, radio_settings())

    async def radio(
        self, user_id: str | None, seed_id: str, limit: int, *, artists: bool = False
    ) -> Radio:
        """At most `limit` items after the seed. `artists`: also accept artist ids."""
        if not self._settings.radio:
            raise FeatureDisabled("Radio is switched off")
        seed = await self._seed(seed_id, artists=artists)
        tracks = await self._catalog.radio(seed.video_id, limit + 1)
        first = next((t for t in tracks if t.video_id == seed.video_id), None)
        if first is None:
            first = await self._catalog.track(seed.video_id)
        return await run_in_threadpool(self._build, user_id or "", seed, first, tracks, limit)

    # ------------------------------------------------------------------ seed

    async def _seed(self, seed_id: str, *, artists: bool) -> _Seed:
        parsed = parse_id(seed_id)
        if isinstance(parsed, VirtualId):
            if parsed.kind == "song":
                found = await run_in_threadpool(self._video_ref, parsed.payload)
                return _Seed(parsed.payload, found)
            if parsed.kind == "artist" and artists:
                return await self._channel_seed(parsed.payload)
            raise InvalidId()
        library = await run_in_threadpool(self._library_seed, parsed.value, artists)
        if isinstance(library, str):
            return await self._channel_seed(library)
        video = library.video_id
        if video is None:
            matches = await self._catalog.search_songs(library.query, 1)
            if not matches:
                raise NotFound("No YouTube Music song to start this radio from")
            video = matches[0].video_id
        return _Seed(video, library.ref, library.from_artist)

    async def _channel_seed(self, channel_id: str) -> _Seed:
        artist = await self._catalog.artist(channel_id)
        if not artist.top_tracks:
            raise NotFound("This artist has no songs on YouTube Music")
        video = artist.top_tracks[0].video_id
        return _Seed(video, await run_in_threadpool(self._video_ref, video), from_artist=True)

    def _video_ref(self, video_id: str) -> TrackRef | None:
        with self._db.read() as conn:
            return tracks_for_videos(conn, [video_id]).get(video_id)

    def _library_seed(self, library_id: str, artists: bool) -> _LibraryTrack | str:
        with self._db.read() as conn:
            try:
                ref = resolve_track(conn, library_id)
            except NotFound:
                if not artists:
                    raise
                return _library_artist(conn, library_id)
            # A library UUID always resolves to a track, never to a virtual id.
            return _video_of(conn, cast("TrackRef", ref))

    # ------------------------------------------------------------------ mapping

    def _build(
        self,
        user_id: str,
        seed: _Seed,
        first: CatalogTrack,
        tracks: list[CatalogTrack],
        limit: int,
    ) -> Radio:
        with self._db.read() as conn:
            refs = tracks_for_videos(conn, [t.video_id for t in tracks])
            ready = [r.id for r in refs.values() if r.status == "ready"]
            if seed.ref is not None and seed.ref.status == "ready":
                ready.append(seed.ref.id)
            library = {s.id: s for s in LibrarySearch(conn).songs_by_id(user_id, ready)}
        seen = {seed.ref.id if seed.ref is not None else song_id(seed.video_id)}
        items: list[Song] = []
        for track in tracks:
            if len(items) >= limit:
                break
            if track.video_id == seed.video_id:
                continue
            ref = refs.get(track.video_id)
            key = ref.id if ref is not None else song_id(track.video_id)
            if key in seen:
                continue
            seen.add(key)
            items.append(_song(track, ref, library))
        return Radio(_song(first, seed.ref, library), items, seed.from_artist)
