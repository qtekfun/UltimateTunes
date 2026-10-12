# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Catalog records ↔ compact JSON, for the `TtlCache` (normalised records, never raw responses).

`encode` works for every record (and lists of them); each `decode_*` rebuilds one type. A value
that does not decode (an older layout after an upgrade) is treated as a cache miss by the
caller.
"""

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, is_dataclass
from typing import Any, cast

from ultimatetunes.search.catalog import (
    AlbumRef,
    ArtistRef,
    CatalogAlbum,
    CatalogAlbumRef,
    CatalogArtist,
    CatalogArtistRef,
    CatalogPlaylist,
    CatalogTrack,
    Thumbnail,
    VideoType,
)

type Obj = Mapping[str, Any]


def encode(value: object) -> str:
    if isinstance(value, list):
        data: object = [asdict(cast("Any", v)) for v in value]
    elif is_dataclass(value) and not isinstance(value, type):
        data = asdict(value)
    else:
        raise TypeError(f"cannot encode {type(value).__name__}")
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def _thumb(data: Obj | None) -> Thumbnail | None:
    return None if data is None else Thumbnail(data["url"], data["width"], data["height"])


def _artists(data: list[Obj]) -> tuple[ArtistRef, ...]:
    return tuple(ArtistRef(a["name"], a["channel_id"]) for a in data)


def _track(data: Obj) -> CatalogTrack:
    album = data["album"]
    return CatalogTrack(
        video_id=data["video_id"],
        title=data["title"],
        artists=_artists(data["artists"]),
        album=None if album is None else AlbumRef(album["name"], album["browse_id"]),
        duration_s=data["duration_s"],
        explicit=data["explicit"],
        video_type=cast("VideoType | None", data["video_type"]),
        year=data["year"],
        track_number=data["track_number"],
        thumbnail=_thumb(data["thumbnail"]),
    )


def _album_ref(data: Obj) -> CatalogAlbumRef:
    return CatalogAlbumRef(
        data["browse_id"],
        data["title"],
        _artists(data["artists"]),
        data["year"],
        _thumb(data["thumbnail"]),
    )


def _artist_ref(data: Obj) -> CatalogArtistRef:
    return CatalogArtistRef(data["channel_id"], data["name"], _thumb(data["thumbnail"]))


def _album(data: Obj) -> CatalogAlbum:
    return CatalogAlbum(
        _album_ref(data["ref"]),
        tuple(_track(t) for t in data["tracks"]),
        data["release_type"],
    )


def _artist(data: Obj) -> CatalogArtist:
    return CatalogArtist(
        _artist_ref(data["ref"]),
        tuple(_track(t) for t in data["top_tracks"]),
        tuple(_album_ref(a) for a in data["albums"]),
    )


def _playlist(data: Obj) -> CatalogPlaylist:
    return CatalogPlaylist(
        data["playlist_id"],
        data["title"],
        tuple(_track(t) for t in data["tracks"]),
        data["unavailable_count"],
    )


def _one[T](build: Callable[[Obj], T]) -> Callable[[str], T]:
    def decode(raw: str) -> T:
        return build(json.loads(raw))

    return decode


def _many[T](build: Callable[[Obj], T]) -> Callable[[str], list[T]]:
    def decode(raw: str) -> list[T]:
        return [build(item) for item in json.loads(raw)]

    return decode


decode_track = _one(_track)
decode_tracks = _many(_track)
decode_album_refs = _many(_album_ref)
decode_artist_refs = _many(_artist_ref)
decode_album = _one(_album)
decode_artist = _one(_artist)
decode_playlist = _one(_playlist)
