# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`YTMusicCatalog`: the `MusicCatalog` on ytmusicapi (anonymous, SPEC §11, T03b).

ytmusicapi is synchronous and built on `requests`, whose `Session` is not promised to be
thread safe, so calls run on a small thread pool where **each thread owns its own `YTMusic`**
(`language="en"` always: `"es"` silently breaks filtered search). Every HTTP request goes
through `YouTubeSession`: HTTPS to `music.youtube.com` only, our timeout, and HTTP errors
raised with their status before ytmusicapi tries to parse an error page.

Errors become catalog errors here (`map_error`): 429/403/gated → `CatalogThrottled`; network
errors and 5xx → `CatalogUnavailable`; an unknown id (ytmusicapi answers "no content" or fails
inside its own parser) → `CatalogNotFound`, never a parse error; a search whose response
cannot be read → `CatalogParseError`. Caching, rate limiting, retries and the circuit breaker
live one layer up (`guard.GuardedCatalog`).
"""

import asyncio
import re
import threading
from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from typing import Any, Literal, override
from urllib.parse import urlsplit

import requests
from ytmusicapi import YTMusic
from ytmusicapi.exceptions import YTMusicGatedError, YTMusicServerError

from ultimatetunes.errors import TunesError
from ultimatetunes.ids.virtual import is_browse_id, is_video_id
from ultimatetunes.search import parse
from ultimatetunes.search.catalog import (
    CatalogAlbum,
    CatalogAlbumRef,
    CatalogArtist,
    CatalogArtistRef,
    CatalogClientError,
    CatalogNotFound,
    CatalogParseError,
    CatalogPlaylist,
    CatalogThrottled,
    CatalogTrack,
    CatalogUnavailable,
)
from ultimatetunes.search.settings import SearchSettings

YTM_HOST = "music.youtube.com"
SearchKind = Literal["songs", "albums", "artists"]
_PLAYLIST_ID = re.compile(r"[A-Za-z0-9_-]{2,64}")
_HTTP_FORBIDDEN = 403
_HTTP_NOT_FOUND = 404
_HTTP_TOO_MANY = 429
_HTTP_SERVER = 500


class HostRefused(requests.RequestException):
    """A request to anything but https://music.youtube.com (SSRF rule)."""


class HttpStatusError(requests.RequestException):
    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status


class YouTubeSession(requests.Session):
    """The only HTTP client ytmusicapi gets."""

    def __init__(self, timeout_s: float) -> None:
        super().__init__()
        self.timeout_s = timeout_s

    @override
    def send(self, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        parts = urlsplit(request.url or "")
        if parts.scheme != "https" or parts.hostname != YTM_HOST:
            raise HostRefused(f"host not allowed: {parts.hostname}")
        kwargs["timeout"] = self.timeout_s
        response = super().send(request, **kwargs)
        if response.status_code >= 400:  # noqa: PLR2004 - any HTTP error
            raise HttpStatusError(response.status_code)
        return response


def map_error(error: Exception, *, lookup: bool) -> Exception:  # noqa: PLR0911 - one per case
    """The catalog error for an exception raised while calling ytmusicapi (others unchanged).

    `lookup`: the call fetched one item by id (album, artist, radio, playlist), where an
    unknown id must be `CatalogNotFound`. Other 4xx answers (403 and 429 are throttling) are
    `CatalogNotFound` on a lookup and `CatalogClientError` otherwise; a 404 outside a lookup
    stays `CatalogUnavailable`.
    """
    missing = CatalogNotFound() if lookup else None
    if isinstance(error, TunesError):
        return error
    if isinstance(error, HttpStatusError):
        if error.status in (_HTTP_FORBIDDEN, _HTTP_TOO_MANY):
            return CatalogThrottled()
        if error.status >= _HTTP_SERVER:
            return CatalogUnavailable()
        if missing is not None:
            return missing
        return CatalogUnavailable() if error.status == _HTTP_NOT_FOUND else CatalogClientError()
    if isinstance(error, requests.RequestException):
        return CatalogUnavailable()
    if isinstance(error, YTMusicGatedError):
        return CatalogThrottled()
    if isinstance(error, YTMusicServerError | KeyError | IndexError | TypeError | ValueError):
        return missing or CatalogParseError()
    return error


class YTMusicBackend:
    """Synchronous ytmusicapi calls, one `YTMusic` per calling thread."""

    def __init__(self, factory: Callable[[], YTMusic]) -> None:
        self._factory = factory
        self._local = threading.local()

    def client(self) -> YTMusic:
        found: YTMusic | None = getattr(self._local, "client", None)
        if found is None:
            found = self._factory()
            self._local.client = found
        return found

    def search(self, query: str, kind: SearchKind, limit: int) -> object:
        return self.client().search(query, filter=kind, limit=limit)

    def album(self, browse_id: str) -> object:
        return self.client().get_album(browse_id)

    def artist(self, channel_id: str) -> object:
        return self.client().get_artist(channel_id)

    def watch_playlist(self, video_id: str, limit: int, *, radio: bool) -> object:
        return self.client().get_watch_playlist(videoId=video_id, limit=limit, radio=radio)

    def playlist(self, playlist_id: str) -> object:
        return self.client().get_playlist(playlist_id, limit=None)


def ytmusic_factory(settings: SearchSettings) -> Callable[[], YTMusic]:
    def build() -> YTMusic:
        return YTMusic(
            language="en",
            location=settings.ytm_location,
            requests_session=YouTubeSession(settings.ytm_timeout_s),
        )

    return build


def _call[T](work: Callable[[], T], lookup: bool) -> T:
    try:
        return work()
    except Exception as error:
        mapped = map_error(error, lookup=lookup)
        if mapped is error:
            raise
        raise mapped from error


class YTMusicCatalog:
    """`MusicCatalog` on a `YTMusicBackend`, run on `executor`. No cache: see `guard`."""

    def __init__(self, backend: YTMusicBackend, executor: Executor) -> None:
        self._backend = backend
        self._executor = executor

    @classmethod
    def build(cls, settings: SearchSettings) -> "YTMusicCatalog":
        """The production catalog. Nothing is contacted until the first call."""
        executor = ThreadPoolExecutor(settings.ytm_threads, thread_name_prefix="ytmusic")
        return cls(YTMusicBackend(ytmusic_factory(settings)), executor)

    async def _run[T](self, work: Callable[[], T], *, lookup: bool) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, _call, work, lookup)

    async def search_songs(self, query: str, limit: int) -> list[CatalogTrack]:
        b = self._backend
        return await self._run(
            lambda: parse.search_songs(b.search(query, "songs", limit)), lookup=False
        )

    async def search_albums(self, query: str, limit: int) -> list[CatalogAlbumRef]:
        b = self._backend
        return await self._run(
            lambda: parse.search_albums(b.search(query, "albums", limit)), lookup=False
        )

    async def search_artists(self, query: str, limit: int) -> list[CatalogArtistRef]:
        b = self._backend
        return await self._run(
            lambda: parse.search_artists(b.search(query, "artists", limit)), lookup=False
        )

    async def album(self, browse_id: str) -> CatalogAlbum:
        if not is_browse_id(browse_id):
            raise CatalogNotFound()
        b = self._backend
        return await self._run(lambda: parse.album(b.album(browse_id), browse_id), lookup=True)

    async def artist(self, channel_id: str) -> CatalogArtist:
        if not is_browse_id(channel_id):
            raise CatalogNotFound()
        b = self._backend
        return await self._run(lambda: parse.artist(b.artist(channel_id), channel_id), lookup=True)

    async def track(self, video_id: str) -> CatalogTrack:
        if not is_video_id(video_id):
            raise CatalogNotFound()
        b = self._backend
        found = await self._run(
            lambda: parse.watch_playlist(b.watch_playlist(video_id, 1, radio=False)), lookup=True
        )
        for item in found:
            if item.video_id == video_id:
                return item
        raise CatalogNotFound()

    async def radio(self, video_id: str, limit: int) -> list[CatalogTrack]:
        if not is_video_id(video_id):
            raise CatalogNotFound()
        b = self._backend
        found = await self._run(
            lambda: parse.watch_playlist(b.watch_playlist(video_id, limit, radio=True)),
            lookup=True,
        )
        if not found:
            raise CatalogNotFound()
        return found[:limit]

    async def playlist(self, playlist_id: str) -> CatalogPlaylist:
        bare = playlist_id.removeprefix("VL")
        if _PLAYLIST_ID.fullmatch(bare) is None:
            raise CatalogNotFound()
        b = self._backend
        return await self._run(lambda: parse.playlist(b.playlist(bare), bare), lookup=True)
