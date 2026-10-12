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
from typing import Literal, Protocol

from ultimatetunes.errors import FeatureNotImplemented, NotFound, UpstreamUnavailable
from ultimatetunes.settings import Settings

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
    """Placeholder until T06 wires ytmusicapi: every call is `FeatureNotImplemented`."""

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


def build_catalog(settings: Settings) -> MusicCatalog:
    """The catalog the api uses: the fake with `UT_FAKE_YOUTUBE=true` (test stack)."""
    if settings.fake_youtube:
        from ultimatetunes.search.fake import FakeMusicCatalog  # noqa: PLC0415

        return FakeMusicCatalog()
    return UnavailableCatalog()
