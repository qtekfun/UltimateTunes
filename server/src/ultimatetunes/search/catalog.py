# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`MusicCatalog`: what the server asks YouTube Music (search, albums, artists, radio, playlists).

Async and typed: implementations return these frozen records, never raw ytmusicapi dicts
(spike T03b). Ids are validated against contracts/ids.md before any call. Errors are
`TunesError`s, so the routers map them without knowing the catalog:
`CatalogNotFound` (→ not found), `CatalogThrottled` / `CatalogUnavailable` /
`CatalogParseError` (→ upstream unavailable).
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from ultimatetunes.errors import FeatureNotImplemented, NotFound, UpstreamUnavailable
from ultimatetunes.settings import Settings

if TYPE_CHECKING:
    from ultimatetunes.core.cache import TtlCache
    from ultimatetunes.core.inflight import InFlight
    from ultimatetunes.core.ratelimit import RateLimiter

VideoType = Literal["ATV", "OMV", "UGC"]


class CatalogNotFound(NotFound):
    default_message = "Not found on YouTube Music"


class CatalogUnavailable(UpstreamUnavailable):
    default_message = "YouTube Music is unavailable"


class CatalogThrottled(CatalogUnavailable):
    default_message = "YouTube Music is throttling requests"


class CatalogParseError(CatalogUnavailable):
    default_message = "Unexpected YouTube Music response"


@dataclass(frozen=True)
class Thumbnail:
    url: str
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True)
class ArtistRef:
    name: str
    channel_id: str | None = None


@dataclass(frozen=True)
class AlbumRef:
    name: str
    browse_id: str | None = None


@dataclass(frozen=True)
class CatalogTrack:
    video_id: str
    title: str
    artists: tuple[ArtistRef, ...]
    album: AlbumRef | None = None
    duration_s: int | None = None
    explicit: bool = False
    video_type: VideoType | None = None
    year: int | None = None
    track_number: int | None = None
    thumbnail: Thumbnail | None = None


@dataclass(frozen=True)
class CatalogAlbumRef:
    browse_id: str
    title: str
    artists: tuple[ArtistRef, ...]
    year: int | None = None
    thumbnail: Thumbnail | None = None


@dataclass(frozen=True)
class CatalogArtistRef:
    channel_id: str
    name: str
    thumbnail: Thumbnail | None = None


@dataclass(frozen=True)
class CatalogAlbum:
    ref: CatalogAlbumRef
    tracks: tuple[CatalogTrack, ...]
    release_type: str | None = None


@dataclass(frozen=True)
class CatalogArtist:
    ref: CatalogArtistRef
    top_tracks: tuple[CatalogTrack, ...]
    albums: tuple[CatalogAlbumRef, ...]


@dataclass(frozen=True)
class CatalogPlaylist:
    playlist_id: str
    title: str
    tracks: tuple[CatalogTrack, ...]
    unavailable_count: int = 0


class MusicCatalog(Protocol):
    async def search_songs(self, query: str, limit: int) -> list[CatalogTrack]: ...

    async def search_albums(self, query: str, limit: int) -> list[CatalogAlbumRef]: ...

    async def search_artists(self, query: str, limit: int) -> list[CatalogArtistRef]: ...

    async def album(self, browse_id: str) -> CatalogAlbum: ...

    async def artist(self, channel_id: str) -> CatalogArtist: ...

    async def track(self, video_id: str) -> CatalogTrack: ...

    async def radio(self, video_id: str, limit: int) -> list[CatalogTrack]:
        """Watch playlist of `video_id`, the seed first."""
        ...

    async def playlist(self, playlist_id: str) -> CatalogPlaylist: ...


class UnavailableCatalog:
    """A catalog that is switched off: every call is `FeatureNotImplemented` (tests)."""

    async def search_songs(self, query: str, limit: int) -> list[CatalogTrack]:
        raise FeatureNotImplemented()

    async def search_albums(self, query: str, limit: int) -> list[CatalogAlbumRef]:
        raise FeatureNotImplemented()

    async def search_artists(self, query: str, limit: int) -> list[CatalogArtistRef]:
        raise FeatureNotImplemented()

    async def album(self, browse_id: str) -> CatalogAlbum:
        raise FeatureNotImplemented()

    async def artist(self, channel_id: str) -> CatalogArtist:
        raise FeatureNotImplemented()

    async def track(self, video_id: str) -> CatalogTrack:
        raise FeatureNotImplemented()

    async def radio(self, video_id: str, limit: int) -> list[CatalogTrack]:
        raise FeatureNotImplemented()

    async def playlist(self, playlist_id: str) -> CatalogPlaylist:
        raise FeatureNotImplemented()


def build_catalog(
    settings: Settings,
    *,
    cache: "TtlCache | None" = None,
    limiter: "RateLimiter | None" = None,
    inflight: "InFlight | None" = None,
) -> MusicCatalog:
    """The catalog the api uses: ytmusicapi behind `GuardedCatalog` (cache, rate limit, retry,
    circuit breaker), or the fake with `UT_FAKE_YOUTUBE=true` (test stack).

    Pass the api's shared cache, rate limiter and in-flight registry. Without them it opens its
    own on the same database file (nothing is opened before the first call).
    """
    # Imported here: they import this module's records.
    from ultimatetunes.core.cache import SqliteTtlCache  # noqa: PLC0415
    from ultimatetunes.core.clock import SystemClock  # noqa: PLC0415
    from ultimatetunes.core.inflight import MemoryInFlight  # noqa: PLC0415
    from ultimatetunes.core.ratelimit import SqliteRateLimiter  # noqa: PLC0415
    from ultimatetunes.db.database import Database  # noqa: PLC0415
    from ultimatetunes.search.fake import FakeMusicCatalog  # noqa: PLC0415
    from ultimatetunes.search.guard import GuardedCatalog  # noqa: PLC0415
    from ultimatetunes.search.settings import SearchSettings  # noqa: PLC0415
    from ultimatetunes.search.ytmusic import YTMusicCatalog  # noqa: PLC0415

    if settings.fake_youtube:
        return FakeMusicCatalog()
    if cache is None or limiter is None:
        db = Database.sqlite(settings.database_file, readers=2)
        clock = SystemClock()
        cache = cache or SqliteTtlCache(db, clock)
        limiter = limiter or SqliteRateLimiter(db, clock)
    search_settings = SearchSettings()
    return GuardedCatalog(
        YTMusicCatalog.build(search_settings),
        cache=cache,
        limiter=limiter,
        inflight=inflight or MemoryInFlight(),
        settings=search_settings,
    )
