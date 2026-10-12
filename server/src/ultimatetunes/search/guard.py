# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`GuardedCatalog`: what stands between the api and YouTube Music (SPEC §11, T03b).

Wraps any `MusicCatalog` (ytmusicapi in production) with:
- a **TTL cache** of normalised records (`TtlCache`, SQLite in v1): search 24 h, album 7 d,
  artist 24 h, track 30 d, radio 1 h, playlist 10 min; unknown ids are cached as not-found
  for 1 h. Every track seen in a search, album, radio or playlist also fills `track:<id>`.
- **single flight** per cache key (`InFlight`): concurrent identical calls share one request.
- a **global rate limit** for music.youtube.com (`RateLimiter` bucket `ytmusic:global`,
  2 req/s, burst 6): a call waits for a token up to `ytm_max_wait_s`, then fails as
  unavailable.
- **one retry** on network errors and 5xx (`CatalogUnavailable`), after a jittered 0.5 to 1.5 s;
  never on not-found, parse errors or throttling.
- a **circuit breaker** on 429/403/gated answers (`CatalogThrottled`): open for 5 min, doubling
  up to 1 h while throttling repeats; while open every uncached call fails fast with
  `CatalogThrottled`. Its state lives in the cache (shared by every api replica) and each
  opening is logged as a warning for the admin (`breaker_state()` for the panel).

All state is in the cache and the rate limiter, so the api stays stateless.
"""

import asyncio
import json
import logging
import secrets
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from starlette.concurrency import run_in_threadpool

from ultimatetunes.core.cache import TtlCache
from ultimatetunes.core.inflight import InFlight
from ultimatetunes.core.ratelimit import Limit, RateLimiter
from ultimatetunes.search import codec
from ultimatetunes.search.catalog import (
    CatalogAlbum,
    CatalogAlbumRef,
    CatalogArtist,
    CatalogArtistRef,
    CatalogNotFound,
    CatalogParseError,
    CatalogPlaylist,
    CatalogThrottled,
    CatalogTrack,
    CatalogUnavailable,
    MusicCatalog,
)
from ultimatetunes.search.settings import SearchSettings
from ultimatetunes.search.text import normalize

log = logging.getLogger(__name__)

HOUR = 3600.0
DAY = 24 * HOUR
TTL_SEARCH = DAY
TTL_ALBUM = 7 * DAY
TTL_ARTIST = DAY
TTL_TRACK = 30 * DAY
TTL_RADIO = HOUR
TTL_PLAYLIST = 600.0
TTL_NOT_FOUND = HOUR
# ytmusicapi returns one page of about 20 whatever the limit; more would cost extra requests.
SEARCH_PAGE = 20
RADIO_SIZE = 50
BUCKET = "ytmusic:global"
BREAKER_OPEN = "ytmusic:breaker:open"
BREAKER_LEVEL = "ytmusic:breaker:level"

Sleep = Callable[[float], Awaitable[None]]


def _jitter() -> float:
    """0.5 to 1.5 s (not security relevant; `secrets` keeps bandit quiet)."""
    return 0.5 + secrets.randbelow(1001) / 1000


@dataclass(frozen=True)
class BreakerState:
    open: bool
    level: int


class GuardedCatalog:
    def __init__(  # noqa: PLR0913 - the shared services it guards with
        self,
        inner: MusicCatalog,
        *,
        cache: TtlCache,
        limiter: RateLimiter,
        inflight: InFlight,
        settings: SearchSettings,
        sleep: Sleep = asyncio.sleep,
        jitter: Callable[[], float] = _jitter,
    ) -> None:
        self._inner = inner
        self._cache = cache
        self._limiter = limiter
        self._inflight = inflight
        self._settings = settings
        self._sleep = sleep
        self._jitter = jitter
        self._limit = Limit(settings.ytm_rate_per_s, settings.ytm_burst)

    # ------------------------------------------------------------------ public API

    async def search_songs(self, query: str, limit: int) -> list[CatalogTrack]:
        key = f"search:songs:{normalize(query)}"
        found = await self._get(
            key,
            TTL_SEARCH,
            lambda: self._inner.search_songs(query, SEARCH_PAGE),
            codec.decode_tracks,
            _tracks_of,
        )
        return found[:limit]

    async def search_albums(self, query: str, limit: int) -> list[CatalogAlbumRef]:
        key = f"search:albums:{normalize(query)}"
        found = await self._get(
            key,
            TTL_SEARCH,
            lambda: self._inner.search_albums(query, SEARCH_PAGE),
            codec.decode_album_refs,
        )
        return found[:limit]

    async def search_artists(self, query: str, limit: int) -> list[CatalogArtistRef]:
        key = f"search:artists:{normalize(query)}"
        found = await self._get(
            key,
            TTL_SEARCH,
            lambda: self._inner.search_artists(query, SEARCH_PAGE),
            codec.decode_artist_refs,
        )
        return found[:limit]

    async def album(self, browse_id: str) -> CatalogAlbum:
        return await self._get(
            f"album:{browse_id}",
            TTL_ALBUM,
            lambda: self._inner.album(browse_id),
            codec.decode_album,
            lambda a: a.tracks,
        )

    async def artist(self, channel_id: str) -> CatalogArtist:
        return await self._get(
            f"artist:{channel_id}",
            TTL_ARTIST,
            lambda: self._inner.artist(channel_id),
            codec.decode_artist,
            lambda a: a.top_tracks,
        )

    async def track(self, video_id: str) -> CatalogTrack:
        return await self._get(
            f"track:{video_id}", TTL_TRACK, lambda: self._inner.track(video_id), codec.decode_track
        )

    async def radio(self, video_id: str, limit: int) -> list[CatalogTrack]:
        found = await self._get(
            f"radio:{video_id}",
            TTL_RADIO,
            lambda: self._inner.radio(video_id, RADIO_SIZE),
            codec.decode_tracks,
            _tracks_of,
        )
        return found[:limit]

    async def playlist(self, playlist_id: str) -> CatalogPlaylist:
        return await self._get(
            f"playlist:{playlist_id}",
            TTL_PLAYLIST,
            lambda: self._inner.playlist(playlist_id),
            codec.decode_playlist,
            lambda p: p.tracks,
        )

    async def breaker_state(self) -> BreakerState:
        is_open = await run_in_threadpool(self._cache.get, BREAKER_OPEN)
        return BreakerState(is_open is not None, await self._level())

    # ------------------------------------------------------------------ machinery

    async def _get[T](
        self,
        key: str,
        ttl: float,
        load: Callable[[], Awaitable[T]],
        decode: Callable[[str], T],
        tracks: Callable[[T], Iterable[CatalogTrack]] | None = None,
    ) -> T:
        cached = await self._cached(key, decode)
        if cached is not None:
            return cached
        if await run_in_threadpool(self._cache.get, f"nf:{key}") is not None:
            raise CatalogNotFound()
        return await self._inflight.run(
            f"catalog:{key}", lambda: self._load(key, ttl, load, tracks)
        )

    async def _cached[T](self, key: str, decode: Callable[[str], T]) -> T | None:
        raw = await run_in_threadpool(self._cache.get, key)
        if raw is None:
            return None
        try:
            return decode(raw)
        except (ValueError, KeyError, TypeError):
            log.warning("dropping an unreadable catalog cache entry")
            return None

    async def _load[T](
        self,
        key: str,
        ttl: float,
        load: Callable[[], Awaitable[T]],
        tracks: Callable[[T], Iterable[CatalogTrack]] | None,
    ) -> T:
        if await run_in_threadpool(self._cache.get, BREAKER_OPEN) is not None:
            raise CatalogThrottled()
        value = await self._attempts(key, load)
        await run_in_threadpool(self._store, key, ttl, value, tracks)
        return value

    async def _attempts[T](self, key: str, load: Callable[[], Awaitable[T]]) -> T:
        retried = False
        while True:
            await self._token()
            try:
                value = await load()
            except CatalogNotFound:
                await run_in_threadpool(self._cache.set, f"nf:{key}", "1", TTL_NOT_FOUND)
                raise
            except CatalogThrottled:
                await self._open_breaker()
                raise
            except CatalogParseError:
                log.warning("unexpected YouTube Music response (%s)", key.split(":", 1)[0])
                raise
            except CatalogUnavailable:
                if retried:
                    raise
                retried = True
                await self._sleep(self._jitter())
                continue
            await self._close_breaker()
            return value

    def _store[T](
        self,
        key: str,
        ttl: float,
        value: T,
        tracks: Callable[[T], Iterable[CatalogTrack]] | None,
    ) -> None:
        self._cache.set(key, codec.encode(value), ttl)
        for item in tracks(value) if tracks else ():
            self._cache.set(f"track:{item.video_id}", codec.encode(item), TTL_TRACK)

    async def _token(self) -> None:
        waited = 0.0
        while True:
            decision = await run_in_threadpool(self._limiter.hit, BUCKET, self._limit)
            if decision.allowed:
                return
            if waited + decision.retry_after_s > self._settings.ytm_max_wait_s:
                raise CatalogUnavailable("Too many YouTube Music requests, try again later")
            await self._sleep(decision.retry_after_s)
            waited += decision.retry_after_s

    async def _level(self) -> int:
        raw = await run_in_threadpool(self._cache.get, BREAKER_LEVEL)
        try:
            return int(json.loads(raw)) if raw is not None else 0
        except (ValueError, TypeError):
            return 0

    async def _open_breaker(self) -> None:
        level = await self._level() + 1
        settings = self._settings
        seconds = min(settings.ytm_breaker_base_s * 2 ** (level - 1), settings.ytm_breaker_max_s)
        await run_in_threadpool(self._cache.set, BREAKER_OPEN, str(level), seconds)
        # The level outlives the opening, so throttling soon after it doubles the next one.
        await run_in_threadpool(
            self._cache.set, BREAKER_LEVEL, str(level), seconds + settings.ytm_breaker_max_s
        )
        log.warning(
            "YouTube Music is throttling: external search and catalog calls paused for %d s"
            " (level %d)",
            seconds,
            level,
        )

    async def _close_breaker(self) -> None:
        if await run_in_threadpool(self._cache.get, BREAKER_LEVEL) is not None:
            await run_in_threadpool(self._cache.delete, BREAKER_LEVEL)


def _tracks_of(value: list[CatalogTrack]) -> Iterable[CatalogTrack]:
    return value
