# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Uploaded playlist files (SPEC §11, T03d): generic CSV, Exportify CSV, Spotify data-export JSON.

Hardening: the caller hands in at most `MAX_FILE_BYTES` (the upload reader stops earlier); the
bytes are decoded as strict UTF-8 with an optional BOM (anything else is `invalid_parameter`);
rows are counted while reading and the 5001st row stops the parse with `payload_too_large`;
each text field is trimmed and cut to `MAX_FIELD_CHARS`. Nothing from the file is ever used as
a path, a URL or SQL text: it only becomes search text and report fields.

Formats:
- `csv`: a header row with `title` and `artist` (several joined with `;`), and optional `album`,
  `duration` (seconds, `m:ss` or `h:mm:ss`) and `isrc`; header names ignore case and spaces.
- `exportify_csv`: the CSV Exportify writes (`Track URI`, `ISRC`, `Track Name`, `Album Name`,
  `Artist Name(s)` joined with `;`, `Duration (ms)`; older exports say `Track Duration (ms)`).
- `spotify_json`: a playlist file of Spotify's "Download your data" export
  (`{"playlists": [{"name", "items": [{"track": {"trackName", "artistName", "albumName",
  "trackUri"}}]}]}`) or one playlist object. A file with several playlists needs `name` to say
  which one to import.

Rows without a title (episodes, local files, blank lines) are skipped.
"""

import csv
import io
import json
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from ultimatetunes.errors import InvalidParameter, PayloadTooLarge

FileFormat = Literal["csv", "exportify_csv", "spotify_json"]
FILE_FORMATS: tuple[FileFormat, ...] = ("csv", "exportify_csv", "spotify_json")
MAX_FILE_BYTES = 1024 * 1024
MAX_ROWS = 5000
MAX_FIELD_CHARS = 500
MAX_NAME_CHARS = 200
# Placeholders some exporters write for a missing value.
_EMPTY = frozenset({"", "undefined", "null", "none"})
_ISRC = re.compile(r"[A-Z]{2}[A-Z0-9]{3}[0-9]{7}")
_CLOCK = re.compile(r"(?:(\d{1,2}):)?(\d{1,3}):(\d{2})")
# A track longer than this is not a song (and not a sane duration).
_MAX_DURATION_S = 24 * 3600


@dataclass(frozen=True)
class SourceItem:
    """One track of the source playlist, as the source describes it."""

    title: str
    artists: tuple[str, ...] = ()
    album: str | None = None
    duration_s: int | None = None
    isrc: str | None = None
    ref: str | None = None
    video_id: str | None = None

    @property
    def artist_text(self) -> str | None:
        return "; ".join(self.artists) or None


@dataclass(frozen=True)
class ParsedFile:
    name: str | None
    items: tuple[SourceItem, ...]


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())[:MAX_FIELD_CHARS]
    return None if cleaned.casefold() in _EMPTY else cleaned


def _artists(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    names = (_text(part) for part in value.split(";"))
    return tuple(dict.fromkeys(n for n in names if n))


def _isrc(value: str | None) -> str | None:
    if value is None:
        return None
    code = value.replace("-", "").replace(" ", "").upper()
    return code if _ISRC.fullmatch(code) else None


def parse_duration(value: str | None) -> int | None:
    """Seconds from `214`, `214.4`, `3:34` or `1:03:34`; None when absent or unreadable."""
    if value is None:
        return None
    seconds: float
    clock = _CLOCK.fullmatch(value)
    if clock is not None:
        hours, minutes, secs = clock.groups()
        if int(secs) >= 60 or (hours is not None and int(minutes) >= 60):  # noqa: PLR2004
            return None
        seconds = int(hours or 0) * 3600 + int(minutes) * 60 + int(secs)
    else:
        try:
            seconds = float(value)
        except ValueError:
            return None
    if not 0 < seconds <= _MAX_DURATION_S:
        return None
    return round(seconds)


def _duration_ms(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        ms = int(value)
    except ValueError:
        return None
    return parse_duration(str(ms / 1000))


def decode(data: bytes) -> str:
    """Strict UTF-8 (an optional BOM is dropped); anything else is `invalid_parameter`."""
    if len(data) > MAX_FILE_BYTES:
        raise PayloadTooLarge("The file is larger than 1 MiB")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InvalidParameter("The file is not valid UTF-8") from None
    if "\x00" in text:
        raise InvalidParameter("The file is not a text file")
    return text


def _too_many() -> PayloadTooLarge:
    return PayloadTooLarge(f"The file has more than {MAX_ROWS} rows")


def _csv_rows(text: str) -> Iterator[list[str]]:
    """Data rows after the header, counted as they are read (the cap stops the parse)."""
    try:
        for count, row in enumerate(csv.reader(io.StringIO(text, newline="")), start=0):
            if count > MAX_ROWS:
                raise _too_many()
            yield row
    except csv.Error as exc:
        raise InvalidParameter(f"The CSV file cannot be read: {exc}") from None


def _header_key(name: str) -> str:
    return "".join(name.split()).casefold()


def _columns(header: Sequence[str]) -> dict[str, int]:
    found: dict[str, int] = {}
    for index, name in enumerate(header):
        found.setdefault(_header_key(name), index)
    return found


def _pick(row: Sequence[str], columns: Mapping[str, int], *names: str) -> str | None:
    for name in names:
        index = columns.get(_header_key(name))
        if index is not None and index < len(row):
            return _text(row[index])
    return None


def _need(columns: Mapping[str, int], fmt: str, *names: str) -> None:
    missing = [n for n in names if _header_key(n) not in columns]
    if missing:
        raise InvalidParameter(f"Not a {fmt} file: missing column(s) {', '.join(missing)}")


def _parse_csv(text: str, *, exportify: bool) -> list[SourceItem]:
    rows = _csv_rows(text)
    header = next(rows, None)
    if header is None:
        raise InvalidParameter("The file is empty")
    columns = _columns(header)
    if exportify:
        _need(columns, "Exportify", "Track Name", "Artist Name(s)")
    else:
        _need(columns, "CSV", "title", "artist")
    items: list[SourceItem] = []
    for row in rows:
        if exportify:
            title = _pick(row, columns, "Track Name")
            artists = _artists(_pick(row, columns, "Artist Name(s)"))
            album = _pick(row, columns, "Album Name")
            duration = _duration_ms(_pick(row, columns, "Duration (ms)", "Track Duration (ms)"))
            ref = _pick(row, columns, "Track URI")
        else:
            title = _pick(row, columns, "title")
            artists = _artists(_pick(row, columns, "artist"))
            album = _pick(row, columns, "album")
            duration = parse_duration(_pick(row, columns, "duration"))
            ref = None
        if title is None:
            continue
        isrc = _isrc(_pick(row, columns, "isrc"))
        items.append(SourceItem(title, artists, album, duration, isrc, ref))
    return items


def _load_json(text: str) -> object:
    try:
        return json.loads(text)
    except (ValueError, RecursionError):
        raise InvalidParameter("The file is not valid JSON") from None


@dataclass(frozen=True)
class _JsonPlaylist:
    name: str | None
    entries: list[object]


def _playlists(document: object) -> list[_JsonPlaylist]:
    if isinstance(document, Mapping) and isinstance(document.get("playlists"), list):
        candidates: list[object] = document["playlists"]
    elif isinstance(document, Mapping) and isinstance(document.get("items"), list):
        candidates = [document]
    else:
        raise InvalidParameter("Not a Spotify playlist file: no `playlists` or `items`")
    found: list[_JsonPlaylist] = []
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            entries = candidate.get("items")
            if isinstance(entries, list):
                found.append(_JsonPlaylist(_text(candidate.get("name")), entries))
    return found


def _choose(playlists: list[_JsonPlaylist], name: str | None) -> _JsonPlaylist:
    if len(playlists) == 1:
        return playlists[0]
    if not playlists:
        raise InvalidParameter("The file has no playlist")
    if name is not None:
        wanted = name.casefold()
        named = [p for p in playlists if p.name is not None and p.name.casefold() == wanted]
        if len(named) == 1:
            return named[0]
    raise InvalidParameter(
        f"The file has {len(playlists)} playlists: set `name` to the one to import"
    )


def _parse_spotify_json(text: str, name: str | None) -> tuple[str | None, list[SourceItem]]:
    playlist = _choose(_playlists(_load_json(text)), name)
    if len(playlist.entries) > MAX_ROWS:
        raise _too_many()
    items: list[SourceItem] = []
    for entry in playlist.entries:
        track = entry.get("track") if isinstance(entry, Mapping) else None
        if not isinstance(track, Mapping):
            continue
        title = _text(track.get("trackName"))
        if title is None:
            continue
        items.append(
            SourceItem(
                title,
                _artists(_text(track.get("artistName"))),
                _text(track.get("albumName")),
                ref=_text(track.get("trackUri")),
            )
        )
    return playlist.name, items


def _name_from_file(filename: str | None) -> str | None:
    if not filename:
        return None
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0] if "." in base else base
    return _text(stem.replace("_", " "))


def parse_file(
    data: bytes, fmt: FileFormat, *, filename: str | None = None, name: str | None = None
) -> ParsedFile:
    """The playlist in an uploaded file. `name` picks a playlist in a multi-playlist JSON."""
    text = decode(data)
    file_name = _name_from_file(filename)
    if fmt == "spotify_json":
        title, items = _parse_spotify_json(text, name)
        found_name = title or file_name
    else:
        items = _parse_csv(text, exportify=fmt == "exportify_csv")
        found_name = file_name
    if not items:
        raise InvalidParameter("The file has no tracks")
    return ParsedFile(found_name[:MAX_NAME_CHARS] if found_name else None, tuple(items))
