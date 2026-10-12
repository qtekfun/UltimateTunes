# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Search: library results first, then YouTube Music results, deduplicated (RF-03).

The three filtered catalog searches (songs, albums, artists) start in parallel with the
library query; whatever has not answered after `search_external_timeout_s` (1.5 s) is
dropped and the answer is library-only for that kind (the call keeps running behind the
single flight and fills the cache for the next search). A failing catalog never fails search.

Deduplication (contracts/ids.md): an external song whose video is archived (`ready`) is
replaced by the library song, and appears once; while its track is `pending` or `failed` it
keeps its `yt:` id and carries that state. External albums and artists already in the
library (same browse or channel id) become the library item.

An empty query (`""`, also sent as two quote characters) lists the library page by page and
never reaches YouTube Music. Each user has a bucket of external searches (`search:user:<id>`,
`UT_SEARCH_USER_RATE_PER_S`, `UT_SEARCH_USER_BURST`); an empty bucket means a library-only
answer, never an error (T22).
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from starlette.concurrency import run_in_threadpool

from ultimatetunes.core.ratelimit import Limit, RateLimiter
from ultimatetunes.db.database import Database
from ultimatetunes.errors import TunesError
from ultimatetunes.ids.resolve import (
    TrackRef,
    TrackStatus,
    albums_for_browse_ids,
    artists_for_channel_ids,
    tracks_for_videos,
)
from ultimatetunes.ids.virtual import song_id
from ultimatetunes.search.catalog import (
    CatalogAlbumRef,
    CatalogArtistRef,
    CatalogTrack,
    MusicCatalog,
)
from ultimatetunes.search.library import LibraryAlbum, LibraryArtist, LibrarySearch, LibrarySong
from ultimatetunes.search.settings import SearchSettings
from ultimatetunes.search.text import tokens

if TYPE_CHECKING:
    from ultimatetunes.core.services import Services

log = logging.getLogger(__name__)

# Largest page per kind a client can ask for.
MAX_COUNT = 500
# A text query merged with YouTube Music pages over at most this many results per kind (the
# merge needs everything before the page). An empty query pages the library without limit.
MAX_MERGED = 1000
EMPTY_QUERIES = ("", '""')
USER_BUCKET = "search:user:"


@dataclass(frozen=True)
class ExternalSong:
    track: CatalogTrack
    # State of a library track created for this video and not archived yet.
    state: TrackStatus | None = None


type Song = LibrarySong | ExternalSong
type Album = LibraryAlbum | CatalogAlbumRef
type Artist = LibraryArtist | CatalogArtistRef


@dataclass(frozen=True)
class Page:
    count: int
    offset: int = 0

    @property
    def end(self) -> int:
        return self.offset + self.count


@dataclass(frozen=True)
class SearchResults:
    artists: Sequence[Artist]
    albums: Sequence[Album]
    songs: Sequence[Song]


@dataclass(frozen=True)
class _Library:
    artists: list[LibraryArtist]
    albums: list[LibraryAlbum]
    songs: list[LibrarySong]


@dataclass(frozen=True)
class _External:
    artists: list[CatalogArtistRef]
    albums: list[CatalogAlbumRef]
    songs: list[CatalogTrack]


@dataclass(frozen=True)
class _Tasks:
    artists: "asyncio.Task[list[CatalogArtistRef]] | None"
    albums: "asyncio.Task[list[CatalogAlbumRef]] | None"
    songs: "asyncio.Task[list[CatalogTrack]] | None"

    def all(self) -> list["asyncio.Task[Any]"]:
        return [t for t in (self.artists, self.albums, self.songs) if t is not None]

    def __bool__(self) -> bool:
        return bool(self.all())


def _start[T](call: "Coroutine[Any, Any, T]") -> "asyncio.Task[T]":
    return asyncio.ensure_future(call)


def _result[T](task: "asyncio.Task[list[T]] | None") -> list[T]:
    """The items of a finished catalog call; nothing if it failed, was cut or never ran."""
    if task is None or not task.done() or task.cancelled():
        return []
    error = task.exception()
    if error is None:
        return task.result()
    if isinstance(error, TunesError):
        log.info("external search unavailable: %s", error.message)
    else:
        log.error("external search failed", exc_info=error)
    return []


@lru_cache(maxsize=1)
def search_settings() -> SearchSettings:
    return SearchSettings()


class SearchService:
    def __init__(
        self,
        db: Database,
        catalog: MusicCatalog,
        settings: SearchSettings,
        limiter: RateLimiter | None = None,
    ) -> None:
        self._db = db
        self._catalog = catalog
        self._settings = settings
        self._limiter = limiter
        self._user_limit = Limit(settings.search_user_rate_per_s, settings.search_user_burst)

    @classmethod
    def of(cls, services: "Services") -> "SearchService":
        return cls(services.db, services.catalog, search_settings(), services.rate_limiter)

    def _external_allowed(self, user_id: str | None) -> bool:
        """The caller's bucket of external searches (`search:user:<id>`) still has a token."""
        if self._limiter is None:
            return True
        # Callers without a user (none today) share one bucket rather than bypassing it.
        decision = self._limiter.hit(USER_BUCKET + (user_id or "-"), self._user_limit)
        if not decision.allowed:
            log.info("external search limit reached for a user, answering from the library")
        return decision.allowed

    async def search(  # noqa: PLR0913 - one page per kind
        self,
        user_id: str | None,
        query: str,
        *,
        artists: Page,
        albums: Page,
        songs: Page,
        external: bool = True,
    ) -> SearchResults:
        list_all = query.strip() in EMPTY_QUERIES
        words = tokens(query)
        use_external = external and self._settings.external_search and not list_all
        if use_external:
            use_external = await run_in_threadpool(self._external_allowed, user_id)
        pages = (artists, albums, songs)
        tasks = self._external(query, pages) if use_external else _Tasks(None, None, None)
        if list_all or words:
            library = await run_in_threadpool(
                self._library, user_id, words, pages, merge=bool(tasks)
            )
        else:
            library = _Library([], [], [])
        if not tasks:
            return SearchResults(library.artists, library.albums, library.songs)
        found = await self._gather(tasks)
        return await run_in_threadpool(self._merge, user_id, library, found, pages)

    # ------------------------------------------------------------------ library

    def _library(
        self,
        user_id: str | None,
        words: list[str],
        pages: tuple[Page, Page, Page],
        *,
        merge: bool,
    ) -> _Library:
        """With `merge`, the first `offset + count` items: the page is cut after merging."""
        uid = user_id or ""

        def window(page: Page) -> tuple[int, int]:
            return (min(page.end, MAX_MERGED), 0) if merge else (page.count, page.offset)

        artists, albums, songs = pages
        with self._db.read() as conn:
            repo = LibrarySearch(conn)
            return _Library(
                repo.artists(uid, words, *window(artists)) if artists.count else [],
                repo.albums(uid, words, *window(albums)) if albums.count else [],
                repo.songs(uid, words, *window(songs)) if songs.count else [],
            )

    # ------------------------------------------------------------------ catalog

    def _external(self, query: str, pages: tuple[Page, Page, Page]) -> "_Tasks":
        artists, albums, songs = pages
        catalog = self._catalog
        return _Tasks(
            _start(catalog.search_artists(query, artists.end)) if artists.count else None,
            _start(catalog.search_albums(query, albums.end)) if albums.count else None,
            _start(catalog.search_songs(query, songs.end)) if songs.count else None,
        )

    async def _gather(self, tasks: "_Tasks") -> _External:
        running = tasks.all()
        _done, pending = await asyncio.wait(
            running, timeout=self._settings.search_external_timeout_s
        )
        for task in pending:
            task.cancel()
        if pending:
            log.info("YouTube Music too slow, answering with library results")
        return _External(_result(tasks.artists), _result(tasks.albums), _result(tasks.songs))

    # ------------------------------------------------------------------ merge

    def _merge(
        self,
        user_id: str | None,
        library: _Library,
        found: _External,
        pages: tuple[Page, Page, Page],
    ) -> SearchResults:
        uid = user_id or ""
        with self._db.read() as conn:
            repo = LibrarySearch(conn)
            tracks = tracks_for_videos(conn, [t.video_id for t in found.songs])
            album_ids = albums_for_browse_ids(conn, [a.browse_id for a in found.albums])
            artist_ids = artists_for_channel_ids(conn, [a.channel_id for a in found.artists])
            ready = [r.id for r in tracks.values() if r.status == "ready"]
            more_songs = {s.id: s for s in repo.songs_by_id(uid, ready)}
            more_albums = {a.id: a for a in repo.albums_by_id(uid, list(album_ids.values()))}
            more_artists = {a.id: a for a in repo.artists_by_id(uid, list(artist_ids.values()))}
        artists_page, albums_page, songs_page = pages
        songs = _merge_songs(library.songs, found.songs, tracks, more_songs)
        albums: list[Album] = _merge_items(
            library.albums,
            found.albums,
            lambda a: album_ids.get(a.browse_id),
            more_albums,
            lambda a: f"ytalbum:{a.browse_id}",
        )
        artists: list[Artist] = _merge_items(
            library.artists,
            found.artists,
            lambda a: artist_ids.get(a.channel_id),
            more_artists,
            lambda a: f"ytartist:{a.channel_id}",
        )
        return SearchResults(
            _page(artists, artists_page), _page(albums, albums_page), _page(songs, songs_page)
        )


def _page[T](items: list[T], page: Page) -> list[T]:
    return items[page.offset : page.offset + page.count]


def _merge_songs(
    library: list[LibrarySong],
    external: list[CatalogTrack],
    tracks: dict[str, TrackRef],
    archived: dict[str, LibrarySong],
) -> list[Song]:
    merged: list[Song] = list(library)
    seen = {s.id for s in library}
    for item in external:
        ref = tracks.get(item.video_id)
        if ref is not None and ref.status == "ready":
            song = archived.get(ref.id)
            if song is not None and song.id not in seen:
                merged.append(song)
                seen.add(song.id)
            continue
        key = song_id(item.video_id)
        if key not in seen:
            merged.append(ExternalSong(item, ref.status if ref else None))
            seen.add(key)
    return merged


def _merge_items[L: (LibraryAlbum, LibraryArtist), E: (CatalogAlbumRef, CatalogArtistRef)](
    library: list[L],
    external: list[E],
    library_id: Callable[[E], str | None],
    in_library: dict[str, L],
    virtual_id: Callable[[E], str],
) -> list[L | E]:
    merged: list[L | E] = list(library)
    seen = {item.id for item in library}
    for item in external:
        found = in_library.get(library_id(item) or "")
        key = found.id if found is not None else virtual_id(item)
        if key in seen:
            continue
        merged.append(found if found is not None else item)
        seen.add(key)
    return merged
