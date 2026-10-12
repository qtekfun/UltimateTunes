# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Registers the audio files of `/music` in the library (PLAN T05).

Only `.opus`, `.m4a`, `.mp3`, `.flac` and `.ogg` files are read (contracts/db/README.md);
anything else, hidden files and symbolic links are skipped. Each file is read with mutagen
through `LibraryStore` (never a path built outside it) and registered in its own
transaction: its artist (by MusicBrainz id, else by normalised name), its album (by
MusicBrainz release id, else by album artist and normalised name) and the track (by path,
`ready`). A file whose path is known and whose size did not change is left alone, unless the
scan is `full`. The scan never deletes anything: a track whose file disappeared stays until
an admin removes it (counted as `missing`).

Tags are read from Vorbis comments (FLAC, Opus, Ogg), ID3 (MP3) and MP4 atoms, using the
MusicBrainz Picard names, including ReplayGain (`REPLAYGAIN_*`, and Opus `R128_*` converted
to the ReplayGain reference). Every `*_norm` column uses `search.text.normalize`.
"""

import contextlib
import logging
import os
import re
import threading
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, cast

import mutagen
from mutagen.id3 import ID3
from mutagen.mp4 import MP4Tags

from ultimatetunes.core.clock import Clock, format_ts
from ultimatetunes.core.storage import LibraryStore
from ultimatetunes.db.database import Database
from ultimatetunes.db.driver import Connection, DatabaseError
from ultimatetunes.errors import PathRejected
from ultimatetunes.ids.uuid7 import new_id
from ultimatetunes.library.covers import COVER_FILES
from ultimatetunes.library.stream import CONTENT_TYPES
from ultimatetunes.search.text import normalize

log = logging.getLogger(__name__)

FORMATS = {".opus": "opus", ".m4a": "m4a", ".mp3": "mp3", ".flac": "flac", ".ogg": "ogg"}
MAX_TEXT = 512
UNKNOWN_ARTIST = "Unknown Artist"
UNKNOWN_ALBUM = "Unknown Album"
# Opus R128 gains are relative to -23 LUFS, ReplayGain to -18 LUFS (RFC 7845, section 5.2.1).
R128_TO_REPLAYGAIN_DB = 5.0

# ID3 text frames and MP4 atoms → the Vorbis comment (Picard) names used below.
_ID3_FRAMES = {
    "TIT2": "title",
    "TPE1": "artist",
    "TALB": "album",
    "TPE2": "albumartist",
    "TSOP": "artistsort",
    "TSO2": "albumartistsort",
    "TRCK": "tracknumber",
    "TPOS": "discnumber",
    "TDRC": "date",
    "TCON": "genre",
    "TSRC": "isrc",
}
_MP4_ATOMS = {
    "\xa9nam": "title",
    "\xa9ART": "artist",
    "\xa9alb": "album",
    "aART": "albumartist",
    "soar": "artistsort",
    "soaa": "albumartistsort",
    "\xa9day": "date",
    "\xa9gen": "genre",
}
# ID3 TXXX descriptions and MP4 freeform names (lowercased) → Vorbis names.
_FREEFORM = {
    "musicbrainz track id": "musicbrainz_trackid",
    "musicbrainz release track id": "musicbrainz_releasetrackid",
    "musicbrainz album id": "musicbrainz_albumid",
    "musicbrainz release group id": "musicbrainz_releasegroupid",
    "musicbrainz artist id": "musicbrainz_artistid",
    "musicbrainz album artist id": "musicbrainz_albumartistid",
    "isrc": "isrc",
}
_NUMBER = re.compile(r"^\s*(\d{1,4})(?:\s*/\s*(\d{1,4}))?")
_YEAR = re.compile(r"^\s*(\d{4})")
_GAIN = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class Tags:
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    album_artist: str | None = None
    artist_sort: str | None = None
    album_artist_sort: str | None = None
    track: int | None = None
    disc: int | None = None
    total_tracks: int | None = None
    total_discs: int | None = None
    year: int | None = None
    genre: str | None = None
    isrc: str | None = None
    mb_recording: str | None = None
    mb_track: str | None = None
    mb_album: str | None = None
    mb_release_group: str | None = None
    mb_artist: str | None = None
    mb_album_artist: str | None = None
    rg_track_gain: float | None = None
    rg_track_peak: float | None = None
    rg_album_gain: float | None = None
    rg_album_peak: float | None = None


@dataclass(frozen=True)
class AudioInfo:
    duration_ms: int | None = None
    bit_rate_kbps: int | None = None
    sample_rate_hz: int | None = None
    channels: int | None = None


@dataclass
class ScanResult:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    failed: int = 0
    missing: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------- tags


def _text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def fields_of(raw: object) -> dict[str, list[str]]:
    """Every tag of a mutagen tag object under its lowercased Vorbis comment name."""
    tags = cast("Any", raw)
    out: dict[str, list[str]] = {}

    def add(name: str, values: Sequence[object]) -> None:
        texts = [_text(v).strip() for v in values]
        out.setdefault(name, []).extend(t for t in texts if t)

    if isinstance(raw, ID3):
        for frame in tags.values():
            frame_id = frame.FrameID
            if frame_id in _ID3_FRAMES:
                add(_ID3_FRAMES[frame_id], [str(t) for t in frame.text])
            elif frame_id == "TXXX":
                desc = str(frame.desc).lower()
                add(_FREEFORM.get(desc, desc), list(frame.text))
            elif frame_id == "UFID" and frame.owner == "http://musicbrainz.org":
                add("musicbrainz_trackid", [frame.data])
    elif isinstance(raw, MP4Tags):
        for key, values in tags.items():
            if key in _MP4_ATOMS:
                add(_MP4_ATOMS[key], list(values))
            elif key in ("trkn", "disk") and values:
                number, total = values[0]
                base = "track" if key == "trkn" else "disc"
                add(f"{base}number", [number] if number else [])
                add(f"{base}total", [total] if total else [])
            elif key.startswith("----:"):
                name = key.rsplit(":", 1)[-1].lower()
                add(_FREEFORM.get(name, name), list(values))
    elif isinstance(tags, Mapping) or hasattr(tags, "as_dict"):
        mapping = tags.as_dict() if hasattr(tags, "as_dict") else tags
        for key, values in mapping.items():
            add(str(key).lower(), values if isinstance(values, list) else [values])
    return out


def _first(fields: Mapping[str, list[str]], *names: str) -> str | None:
    for name in names:
        values = fields.get(name)
        if values:
            return values[0][:MAX_TEXT]
    return None


def _number(text: str | None) -> tuple[int | None, int | None]:
    match = _NUMBER.match(text or "")
    if match is None:
        return None, None
    total = match.group(2)
    return int(match.group(1)), int(total) if total else None


def _gain(text: str | None) -> float | None:
    match = _GAIN.match(text or "")
    return float(match.group(1)) if match else None


def _r128(text: str | None) -> float | None:
    """`R128_*_GAIN` (Q7.8 fixed point, -23 LUFS) as a ReplayGain value in dB."""
    try:
        value = int((text or "").strip())
    except ValueError:
        return None
    return round(value / 256 + R128_TO_REPLAYGAIN_DB, 2)


def read_tags(fields: Mapping[str, list[str]]) -> Tags:
    track, total_tracks = _number(_first(fields, "tracknumber"))
    disc, total_discs = _number(_first(fields, "discnumber"))
    total_tracks = total_tracks or _number(_first(fields, "tracktotal", "totaltracks"))[0]
    total_discs = total_discs or _number(_first(fields, "disctotal", "totaldiscs"))[0]
    year_match = _YEAR.match(_first(fields, "date", "year", "originaldate") or "")
    track_gain = _gain(_first(fields, "replaygain_track_gain"))
    album_gain = _gain(_first(fields, "replaygain_album_gain"))
    if track_gain is None:
        track_gain = _r128(_first(fields, "r128_track_gain"))
    if album_gain is None:
        album_gain = _r128(_first(fields, "r128_album_gain"))
    return Tags(
        title=_first(fields, "title"),
        artist=_first(fields, "artist"),
        album=_first(fields, "album"),
        album_artist=_first(fields, "albumartist", "album artist"),
        artist_sort=_first(fields, "artistsort"),
        album_artist_sort=_first(fields, "albumartistsort"),
        track=track,
        disc=disc,
        total_tracks=total_tracks,
        total_discs=total_discs,
        year=int(year_match.group(1)) if year_match else None,
        genre=_first(fields, "genre"),
        isrc=_first(fields, "isrc"),
        mb_recording=_first(fields, "musicbrainz_trackid"),
        mb_track=_first(fields, "musicbrainz_releasetrackid"),
        mb_album=_first(fields, "musicbrainz_albumid"),
        mb_release_group=_first(fields, "musicbrainz_releasegroupid"),
        mb_artist=_first(fields, "musicbrainz_artistid"),
        mb_album_artist=_first(fields, "musicbrainz_albumartistid"),
        rg_track_gain=track_gain,
        rg_track_peak=_gain(_first(fields, "replaygain_track_peak")),
        rg_album_gain=album_gain,
        rg_album_peak=_gain(_first(fields, "replaygain_album_peak")),
    )


def read_info(info: object, size: int) -> AudioInfo:
    length = getattr(info, "length", None)
    duration_ms = round(length * 1000) if isinstance(length, int | float) and length > 0 else None
    bitrate = getattr(info, "bitrate", None)
    kbps = round(bitrate / 1000) if isinstance(bitrate, int) and bitrate > 0 else None
    if kbps is None and duration_ms:
        kbps = round(size * 8 / duration_ms)
    sample_rate = getattr(info, "sample_rate", None)
    channels = getattr(info, "channels", None)
    return AudioInfo(
        duration_ms=duration_ms,
        bit_rate_kbps=kbps,
        sample_rate_hz=sample_rate if isinstance(sample_rate, int) and sample_rate > 0 else None,
        channels=channels if isinstance(channels, int) and channels > 0 else None,
    )


# ---------------------------------------------------------------------- files


def list_files(store: LibraryStore) -> Iterator[str]:
    """Relative paths of the regular, visible files of the library, in a stable order.

    `LibraryStore` has no listing call yet (coordinator: SPEC section 11 / PR notes); the
    local store's root is walked without following symbolic links, and every path still goes
    through the store's checks before it is opened.
    """
    root = getattr(store, "root", None)
    if not isinstance(root, Path) or not root.is_dir():
        return
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        base = Path(directory)
        parts = base.relative_to(root).parts
        for name in sorted(files):
            full = base / name
            if name.startswith(".") or full.is_symlink() or not full.is_file():
                continue
            with contextlib.suppress(PathRejected):
                yield store.check(PurePosixPath(*parts, name).as_posix())


# ---------------------------------------------------------------------- registration


@dataclass(frozen=True)
class ScannedFile:
    path: str
    fmt: str
    size: int
    tags: Tags
    info: AudioInfo
    cover: str | None


@dataclass(frozen=True)
class _Known:
    id: str
    size_bytes: int | None


class LibraryScanner:
    def __init__(self, db: Database, store: LibraryStore, clock: Clock) -> None:
        self._db = db
        self._store = store
        self._clock = clock

    def _now(self) -> str:
        return format_ts(self._clock.now())

    def scan(self, *, full: bool = False, stop: threading.Event | None = None) -> ScanResult:
        result = ScanResult()
        seen: set[str] = set()
        for path in list_files(self._store):
            if stop is not None and stop.is_set():
                return result
            fmt = FORMATS.get(PurePosixPath(path).suffix.lower())
            if fmt is None:
                result.skipped += 1
                continue
            seen.add(path)
            try:
                outcome = self.register(path, fmt, full=full)
            except (mutagen.MutagenError, OSError, PathRejected, DatabaseError, ValueError) as exc:
                result.failed += 1
                result.errors.append(f"{path}: {type(exc).__name__}")
                log.warning("library scan: cannot read %s (%s)", path, type(exc).__name__)
                continue
            setattr(result, outcome, getattr(result, outcome) + 1)
        result.missing = self._missing(seen)
        log.info(
            "library scan: %d added, %d updated, %d unchanged, %d skipped, %d failed, %d missing",
            result.added,
            result.updated,
            result.unchanged,
            result.skipped,
            result.failed,
            result.missing,
        )
        return result

    def _missing(self, seen: set[str]) -> int:
        with self._db.read() as conn:
            rows = conn.execute(
                "SELECT path FROM tracks WHERE status = 'ready' AND path IS NOT NULL"
            ).fetchall()
        return sum(1 for row in rows if str(row["path"]) not in seen)

    def register(self, path: str, fmt: str, *, full: bool = False) -> str:
        """Registers one file; returns `added`, `updated` or `unchanged`."""
        size = self._store.size(path)
        with self._db.read() as conn:
            row = conn.execute(
                "SELECT id, size_bytes FROM tracks WHERE path = ?", (path,)
            ).fetchone()
        known = None if row is None else _Known(str(row["id"]), _int(row["size_bytes"]))
        if known is not None and known.size_bytes == size and not full:
            return "unchanged"
        with self._store.open_read(path) as handle:
            audio = mutagen.File(handle)
        if audio is None:
            raise ValueError("not an audio file mutagen can read")
        tags = read_tags(fields_of(audio.tags))
        info = read_info(audio.info, size)
        cover = self._cover_next_to(path)
        with self._db.transaction() as conn:
            scanned = ScannedFile(path, fmt, size, tags, info, cover)
            _Writer(conn, self._now(), self._clock).track(known.id if known else None, scanned)
        return "updated" if known else "added"

    def _cover_next_to(self, path: str) -> str | None:
        folder = str(PurePosixPath(path).parent)
        for name in COVER_FILES:
            candidate = name if folder == "." else f"{folder}/{name}"
            with contextlib.suppress(PathRejected, OSError):
                if self._store.exists(candidate):
                    return candidate
        return None


def _int(value: object) -> int | None:
    return value if isinstance(value, int) else None


class _Writer:
    """The writes of one file, inside the caller's transaction."""

    def __init__(self, conn: Connection, now: str, clock: Clock) -> None:
        self.conn = conn
        self.now = now
        self.clock = clock

    def artist(self, name: str, sort_name: str | None, mbid: str | None) -> str:
        if mbid:
            row = self.conn.execute(
                "SELECT id FROM artists WHERE musicbrainz_id = ?", (mbid,)
            ).fetchone()
            if row is not None:
                return str(row["id"])
        norm = normalize(name)
        row = self.conn.execute(
            "SELECT id, musicbrainz_id FROM artists WHERE name_norm = ? ORDER BY id LIMIT 1",
            (norm,),
        ).fetchone()
        if row is not None and (not mbid or row["musicbrainz_id"] in (None, mbid)):
            if mbid and row["musicbrainz_id"] is None:
                self.conn.execute(
                    "UPDATE artists SET musicbrainz_id = ?, updated_at = ? WHERE id = ?",
                    (mbid, self.now, row["id"]),
                )
            return str(row["id"])
        artist_id = new_id(self.clock)
        self.conn.execute(
            "INSERT INTO artists (id, name, name_norm, sort_name, musicbrainz_id, created_at,"
            " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (artist_id, name, norm, sort_name, mbid or None, self.now, self.now),
        )
        return artist_id

    def album(self, artist_id: str, name: str, tags: Tags, cover: str | None) -> str:
        row = None
        if tags.mb_album:
            row = self.conn.execute(
                "SELECT id, cover_path FROM albums WHERE musicbrainz_release_id = ?",
                (tags.mb_album,),
            ).fetchone()
        norm = normalize(name)
        if row is None:
            row = self.conn.execute(
                "SELECT id, cover_path FROM albums WHERE artist_id = ? AND name_norm = ?"
                " ORDER BY id LIMIT 1",
                (artist_id, norm),
            ).fetchone()
        if row is not None:
            if row["cover_path"] is None and cover is not None:
                self.conn.execute(
                    "UPDATE albums SET cover_path = ?, updated_at = ? WHERE id = ?",
                    (cover, self.now, row["id"]),
                )
            return str(row["id"])
        album_id = new_id(self.clock)
        self.conn.execute(
            "INSERT INTO albums (id, artist_id, name, name_norm, year, genre, total_tracks,"
            " total_discs, musicbrainz_release_id, musicbrainz_release_group_id, cover_path,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                album_id,
                artist_id,
                name,
                norm,
                tags.year,
                tags.genre,
                tags.total_tracks,
                tags.total_discs,
                tags.mb_album,
                tags.mb_release_group,
                cover,
                self.now,
                self.now,
            ),
        )
        return album_id

    def track(self, track_id: str | None, file: "ScannedFile") -> str:
        path, fmt, size, tags, info = file.path, file.fmt, file.size, file.tags, file.info
        cover = file.cover
        title = tags.title or PurePosixPath(path).stem[:MAX_TEXT]
        artist_name = tags.artist or tags.album_artist or UNKNOWN_ARTIST
        artist_id = self.artist(artist_name, tags.artist_sort, tags.mb_artist)
        album_artist = tags.album_artist or artist_name
        album_artist_id = (
            artist_id
            if album_artist == artist_name
            else self.artist(album_artist, tags.album_artist_sort, tags.mb_album_artist)
        )
        album_id = self.album(album_artist_id, tags.album or UNKNOWN_ALBUM, tags, cover)
        values = (
            title,
            normalize(title),
            artist_id,
            album_id,
            artist_name,
            tags.album or UNKNOWN_ALBUM,
            tags.track,
            tags.disc,
            tags.year,
            tags.genre,
            info.duration_ms,
            fmt,
            CONTENT_TYPES[fmt],
            size,
            info.bit_rate_kbps,
            info.sample_rate_hz,
            info.channels,
            tags.rg_track_gain,
            tags.rg_track_peak,
            tags.rg_album_gain,
            tags.rg_album_peak,
            tags.mb_recording,
            tags.mb_track,
            tags.isrc,
            self.now,
        )
        columns = (
            "title = ?, title_norm = ?, artist_id = ?, album_id = ?, artist_name = ?,"
            " album_name = ?, track_number = ?, disc_number = ?, year = ?, genre = ?,"
            " duration_ms = ?, format = ?, content_type = ?, size_bytes = ?, bit_rate_kbps = ?,"
            " sample_rate_hz = ?, channels = ?, rg_track_gain_db = ?, rg_track_peak = ?,"
            " rg_album_gain_db = ?, rg_album_peak = ?, musicbrainz_recording_id = ?,"
            " musicbrainz_track_id = ?, isrc = ?, updated_at = ?"
        )
        if track_id is not None:
            self.conn.execute(f"UPDATE tracks SET {columns} WHERE id = ?", (*values, track_id))  # noqa: S608  # nosec B608
            return track_id
        track_id = new_id(self.clock)
        self.conn.execute(
            "INSERT INTO tracks (id, status, path, created_at, archived_at, title, title_norm,"
            " artist_id, album_id, artist_name, album_name, track_number, disc_number, year,"
            " genre, duration_ms, format, content_type, size_bytes, bit_rate_kbps,"
            " sample_rate_hz, channels, rg_track_gain_db, rg_track_peak, rg_album_gain_db,"
            " rg_album_peak, musicbrainz_recording_id, musicbrainz_track_id, isrc, updated_at)"
            " VALUES (?, 'ready', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
            " ?, ?, ?, ?, ?, ?, ?)",
            (track_id, path, self.now, self.now, *values),
        )
        return track_id
