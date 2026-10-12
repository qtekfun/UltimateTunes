# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Parsing of every id that crosses an API boundary (contracts/ids.md).

- Library ids: lowercase UUIDs (uppercase input is lowercased).
- Virtual ids: `yt:<videoId>` (song), `ytalbum:<browseId>`, `ytartist:<channelId>`.
- Cover art ids: `al-<uuid>`, `ar-<uuid>`, `pl-<uuid>`, or a virtual id.

Anything else (unknown prefix, empty or malformed payload, whitespace, URL-encoded tricks) is
`InvalidId` before any lookup: OpenSubsonic error 70, `/ut/v1` problem `invalid_id`.
"""

import re
from dataclasses import dataclass
from typing import Literal

from ultimatetunes.errors import InvalidId

VirtualKind = Literal["song", "album", "artist"]
CoverKind = Literal["album", "artist", "playlist", "song", "external_album", "external_artist"]

SONG_PREFIX = "yt:"
ALBUM_PREFIX = "ytalbum:"
ARTIST_PREFIX = "ytartist:"

_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_BROWSE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_PREFIXES: tuple[tuple[str, VirtualKind, re.Pattern[str]], ...] = (
    (SONG_PREFIX, "song", _VIDEO_ID),
    (ALBUM_PREFIX, "album", _BROWSE_ID),
    (ARTIST_PREFIX, "artist", _BROWSE_ID),
)
_KIND_PREFIX: dict[VirtualKind, str] = {kind: prefix for prefix, kind, _ in _PREFIXES}
_KIND_PATTERN: dict[VirtualKind, re.Pattern[str]] = {kind: rx for _, kind, rx in _PREFIXES}
_COVER_PREFIXES: dict[str, CoverKind] = {"al-": "album", "ar-": "artist", "pl-": "playlist"}
_VIRTUAL_COVER: dict[VirtualKind, CoverKind] = {
    "song": "song",
    "album": "external_album",
    "artist": "external_artist",
}


@dataclass(frozen=True)
class LibraryId:
    """A library row id: a lowercase UUID."""

    value: str


@dataclass(frozen=True)
class VirtualId:
    """A YouTube Music item: `kind` and the YouTube id (`payload`)."""

    kind: VirtualKind
    payload: str

    @property
    def text(self) -> str:
        return _KIND_PREFIX[self.kind] + self.payload


@dataclass(frozen=True)
class CoverId:
    """A parsed `coverArt` value: what it shows and the library or YouTube id behind it."""

    kind: CoverKind
    value: str


def is_video_id(value: str) -> bool:
    return _VIDEO_ID.fullmatch(value) is not None


def is_browse_id(value: str) -> bool:
    """Album browse ids and artist channel ids (the generic contract regex)."""
    return _BROWSE_ID.fullmatch(value) is not None


def is_uuid(value: str) -> bool:
    return _UUID.fullmatch(value) is not None


def virtual(kind: VirtualKind, payload: str) -> VirtualId:
    """A checked virtual id; `InvalidId` when the payload breaks the contract regex."""
    if _KIND_PATTERN[kind].fullmatch(payload) is None:
        raise InvalidId()
    return VirtualId(kind, payload)


def song_id(video_id: str) -> str:
    return virtual("song", video_id).text


def album_id(browse_id: str) -> str:
    return virtual("album", browse_id).text


def artist_id(channel_id: str) -> str:
    return virtual("artist", channel_id).text


def parse_id(text: str) -> LibraryId | VirtualId:
    """Any id: a library UUID or a virtual id."""
    for prefix, kind, _ in _PREFIXES:
        if text.startswith(prefix):
            return virtual(kind, text[len(prefix) :])
    lowered = text.lower()
    if is_uuid(lowered):
        return LibraryId(lowered)
    raise InvalidId()


def parse_kind(text: str, kind: VirtualKind) -> LibraryId | VirtualId:
    """An id where only library ids and virtual ids of `kind` make sense (e.g. a song)."""
    parsed = parse_id(text)
    if isinstance(parsed, VirtualId) and parsed.kind != kind:
        raise InvalidId()
    return parsed


def cover_id(kind: Literal["album", "artist", "playlist"], library_id: str) -> str:
    """`al-<uuid>`, `ar-<uuid>` or `pl-<uuid>`."""
    if not is_uuid(library_id):
        raise InvalidId()
    return f"{kind[:2]}-{library_id}"


def parse_cover_id(text: str) -> CoverId:
    """A `coverArt` value; never a path."""
    library = _COVER_PREFIXES.get(text[:3])
    if library is not None:
        value = text[3:].lower()
        if not is_uuid(value):
            raise InvalidId()
        return CoverId(library, value)
    parsed = parse_id(text)
    if isinstance(parsed, LibraryId):
        raise InvalidId()
    return CoverId(_VIRTUAL_COVER[parsed.kind], parsed.payload)
