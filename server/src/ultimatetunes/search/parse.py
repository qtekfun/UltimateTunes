# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""ytmusicapi responses → catalog records (shapes recorded in spike T03b).

Pure functions over the decoded JSON, tested with trimmed real responses
(tests/search/fixtures). Lists are parsed leniently: an item without the fields we need (no
`videoId`, an unavailable entry, a podcast in the results) is skipped, never an error. A
response whose top-level shape is wrong raises `CatalogParseError` (a YouTube Music layout
change, the canary's business).

Thumbnails keep only the four approved image hosts over HTTPS (SPEC §11); the largest size is
picked and Google image URLs are rewritten to 544 px instead of storing several sizes.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import cast
from urllib.parse import urlsplit

from ultimatetunes.ids.virtual import is_browse_id, is_video_id
from ultimatetunes.search.catalog import (
    AlbumRef,
    ArtistRef,
    CatalogAlbum,
    CatalogAlbumRef,
    CatalogArtist,
    CatalogArtistRef,
    CatalogParseError,
    CatalogPlaylist,
    CatalogTrack,
    Thumbnail,
    VideoType,
)

type Json = Mapping[str, object]

IMAGE_HOSTS = frozenset(
    {"yt3.googleusercontent.com", "lh3.googleusercontent.com", "yt3.ggpht.com", "i.ytimg.com"}
)
_GOOGLE_HOSTS = frozenset(IMAGE_HOSTS - {"i.ytimg.com"})
COVER_SIZE = 544
_SIZE_WH = re.compile(r"=w\d+-h\d+")
_SIZE_S = re.compile(r"=s\d+")
_DURATION = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})")
_VIDEO_TYPES: dict[str, VideoType] = {
    "MUSIC_VIDEO_TYPE_ATV": "ATV",
    "MUSIC_VIDEO_TYPE_OMV": "OMV",
    "MUSIC_VIDEO_TYPE_UGC": "UGC",
}


def _mapping(value: object) -> Json | None:
    return cast("Json", value) if isinstance(value, Mapping) else None


def _items(value: object) -> list[Json]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return []
    return [item for item in (_mapping(v) for v in value) if item is not None]


def _text(data: Json, key: str) -> str | None:
    value = data.get(key)
    return value.strip() or None if isinstance(value, str) else None


def _year(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _duration(data: Json) -> int | None:
    seconds = data.get("duration_seconds")
    if isinstance(seconds, int) and not isinstance(seconds, bool) and seconds >= 0:
        return seconds
    for key in ("duration", "length"):
        text = _text(data, key)
        match = _DURATION.fullmatch(text) if text else None
        if match:
            hours, minutes, secs = match.groups()
            return int(hours or 0) * 3600 + int(minutes) * 60 + int(secs)
    return None


def _sized(url: str) -> str:
    if urlsplit(url).hostname not in _GOOGLE_HOSTS:
        return url
    if _SIZE_WH.search(url):
        return _SIZE_WH.sub(f"=w{COVER_SIZE}-h{COVER_SIZE}", url, count=1)
    return _SIZE_S.sub(f"=s{COVER_SIZE}", url, count=1)


def _approved_image_url(url: str) -> bool:
    """HTTPS on an approved host, written plainly: no explicit port, no userinfo (`@`)."""
    parts = urlsplit(url)
    # `netloc == hostname` also rules out uppercase hosts and an empty port (`host:`).
    return (
        parts.scheme == "https" and parts.hostname in IMAGE_HOSTS and parts.netloc == parts.hostname
    )


def thumbnail(value: object) -> Thumbnail | None:
    """The largest thumbnail on an approved host (HTTPS), or None."""
    best: Thumbnail | None = None
    for item in _items(value):
        url = _text(item, "url")
        if url is None:
            continue
        if not _approved_image_url(url):
            continue
        width = item.get("width")
        height = item.get("height")
        thumb = Thumbnail(
            url,
            width if isinstance(width, int) else None,
            height if isinstance(height, int) else None,
        )
        if best is None or (thumb.width or 0) > (best.width or 0):
            best = thumb
    if best is None:
        return None
    sized = _sized(best.url)
    if sized != best.url:
        return Thumbnail(sized, COVER_SIZE, COVER_SIZE)
    return best


def artists(value: object) -> tuple[ArtistRef, ...]:
    found: list[ArtistRef] = []
    for item in _items(value):
        name = _text(item, "name")
        if name is None:
            continue
        channel = _text(item, "id")
        found.append(ArtistRef(name, channel if channel and is_browse_id(channel) else None))
    return tuple(found)


def _album_ref(value: object) -> AlbumRef | None:
    data = _mapping(value)
    if data is None:
        return None
    name = _text(data, "name")
    if name is None:
        return None
    browse = _text(data, "id")
    return AlbumRef(name, browse if browse and is_browse_id(browse) else None)


def track(
    data: Json, *, album: AlbumRef | None = None, year: int | None = None
) -> CatalogTrack | None:
    """A song from a search result, an album page, a watch playlist or a playlist."""
    video_id = _text(data, "videoId")
    title = _text(data, "title")
    if video_id is None or not is_video_id(video_id) or title is None:
        return None
    if data.get("isAvailable") is False:
        return None
    video_type = data.get("videoType")
    number = data.get("trackNumber")
    return CatalogTrack(
        video_id=video_id,
        title=title,
        artists=artists(data.get("artists")),
        album=_album_ref(data.get("album")) or album,
        duration_s=_duration(data),
        explicit=data.get("isExplicit") is True,
        video_type=_VIDEO_TYPES.get(video_type) if isinstance(video_type, str) else None,
        year=_year(data.get("year")) or year,
        track_number=number if isinstance(number, int) and number > 0 else None,
        thumbnail=thumbnail(data.get("thumbnails") or data.get("thumbnail")),
    )


def _list(value: object) -> list[Json]:
    if not isinstance(value, list):
        raise CatalogParseError()
    return _items(value)


def _object(value: object) -> Json:
    data = _mapping(value)
    if data is None:
        raise CatalogParseError()
    return data


def search_songs(value: object) -> list[CatalogTrack]:
    found = (track(item) for item in _list(value) if item.get("resultType") in (None, "song"))
    return [t for t in found if t is not None]


def album_ref(data: Json) -> CatalogAlbumRef | None:
    browse = _text(data, "browseId")
    title = _text(data, "title")
    if browse is None or not is_browse_id(browse) or title is None:
        return None
    return CatalogAlbumRef(
        browse,
        title,
        artists(data.get("artists")),
        _year(data.get("year")),
        thumbnail(data.get("thumbnails")),
    )


def search_albums(value: object) -> list[CatalogAlbumRef]:
    found = (album_ref(item) for item in _list(value) if item.get("resultType") in (None, "album"))
    return [a for a in found if a is not None]


def artist_ref(data: Json, channel_id: str | None = None) -> CatalogArtistRef | None:
    channel = channel_id or _text(data, "browseId")
    name = _text(data, "artist") or _text(data, "name")
    if channel is None or not is_browse_id(channel) or name is None:
        return None
    return CatalogArtistRef(channel, name, thumbnail(data.get("thumbnails")))


def search_artists(value: object) -> list[CatalogArtistRef]:
    found = (
        artist_ref(item) for item in _list(value) if item.get("resultType") in (None, "artist")
    )
    return [a for a in found if a is not None]


def album(value: object, browse_id: str) -> CatalogAlbum:
    """`get_album`: its tracks carry the album name as a plain string and no thumbnail."""
    data = _object(value)
    title = _text(data, "title")
    if title is None:
        raise CatalogParseError()
    year = _year(data.get("year"))
    ref = CatalogAlbumRef(
        browse_id, title, artists(data.get("artists")), year, thumbnail(data.get("thumbnails"))
    )
    album_ref_ = AlbumRef(title, browse_id)
    tracks: list[CatalogTrack] = []
    for item in _items(data.get("tracks")):
        found = track({**item, "album": None}, album=album_ref_, year=year)
        if found is not None:
            tracks.append(found if found.thumbnail else _with_thumbnail(found, ref.thumbnail))
    release = _text(data, "type")
    return CatalogAlbum(ref, tuple(tracks), release.lower() if release else None)


def _with_thumbnail(found: CatalogTrack, thumb: Thumbnail | None) -> CatalogTrack:
    return found if thumb is None else replace(found, thumbnail=thumb)


def artist(value: object, channel_id: str) -> CatalogArtist:
    """`get_artist`: top songs and the albums and singles shown on the page."""
    data = _object(value)
    ref = artist_ref(data, channel_id)
    if ref is None:
        raise CatalogParseError()
    songs = _mapping(data.get("songs")) or {}
    top = (track(item) for item in _items(songs.get("results")))
    albums: list[CatalogAlbumRef] = []
    for section in ("albums", "singles"):
        results = (_mapping(data.get(section)) or {}).get("results")
        for item in _items(results):
            fallback = [{"name": ref.name, "id": channel_id}]
            found = album_ref({**item, "artists": item.get("artists") or fallback})
            if found is not None:
                albums.append(found)
    return CatalogArtist(ref, tuple(t for t in top if t is not None), tuple(albums))


def watch_playlist(value: object) -> list[CatalogTrack]:
    """`get_watch_playlist`: the seed first, then the radio."""
    data = _object(value)
    found = (track(item) for item in _list(data.get("tracks")))
    return [t for t in found if t is not None]


def playlist(value: object, playlist_id: str) -> CatalogPlaylist:
    """`get_playlist`: unavailable entries (no video id, `isAvailable: false`, or silently left
    out of `trackCount`) are counted, not returned."""
    data = _object(value)
    entries = _list(data.get("tracks"))
    tracks = [t for t in (track(item) for item in entries) if t is not None]
    count = data.get("trackCount")
    hidden = count - len(entries) if isinstance(count, int) and count > len(entries) else 0
    title = _text(data, "title") or playlist_id
    return CatalogPlaylist(playlist_id, title, tuple(tracks), len(entries) - len(tracks) + hidden)
