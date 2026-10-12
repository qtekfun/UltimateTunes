# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tags with mutagen: Vorbis comments in Ogg/Opus, iTunes atoms in M4A (RF-04).

Names follow MusicBrainz Picard's mapping, so other tools and the library scan read them:
`MUSICBRAINZ_TRACKID` is the **recording** id and `MUSICBRAINZ_RELEASETRACKID` the track id.
ReplayGain 2.0 goes into `REPLAYGAIN_*` in both formats (`-7.85 dB`, peak `0.993000`); Opus
also gets `R128_TRACK_GAIN`/`R128_ALBUM_GAIN` (RFC 7845: Q7.8 integers relative to -23 LUFS,
i.e. the ReplayGain value minus 5 dB). Writing tags replaces whatever the file held.
"""

import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from mutagen import MutagenError
from mutagen.mp4 import MP4, MP4FreeForm
from mutagen.oggopus import OggOpus

from ultimatetunes.tagging.model import M4A, OPUS, ArchiveKind, ReplayGain, TrackMetadata

# mutagen ships no type hints for these: typed entry points, the files themselves are `Any`.
_open_opus: Callable[[Path], Any] = OggOpus
_open_mp4: Callable[[Path], Any] = MP4
_freeform_value: Callable[[bytes], object] = MP4FreeForm
_ITUNES = "----:com.apple.iTunes:"
_R128_OFFSET_DB = 5.0
_GAIN = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*dB\s*$", re.IGNORECASE)


class TaggingError(Exception):
    """mutagen could not read or write the file."""


def _clean(value: str) -> str:
    """No NUL and no lone surrogate (not encodable as UTF-8)."""
    return "".join(ch for ch in value if ch != "\x00" and not "\ud800" <= ch <= "\udfff").strip()


def _gain(value: float) -> str:
    return f"{value:.2f} dB"


def _peak(value: float) -> str:
    return f"{value:.6f}"


def _r128(gain_db: float) -> str:
    q78 = round((gain_db - _R128_OFFSET_DB) * 256)
    return str(max(-32768, min(32767, q78)))


def _gain_pairs(gain: ReplayGain) -> list[tuple[str, str | None]]:
    album_gain = None if gain.album_gain_db is None else _gain(gain.album_gain_db)
    album_peak = None if gain.album_peak is None else _peak(gain.album_peak)
    return [
        ("replaygain_track_gain", _gain(gain.track_gain_db)),
        ("replaygain_track_peak", _peak(gain.track_peak)),
        ("replaygain_album_gain", album_gain),
        ("replaygain_album_peak", album_peak),
    ]


def _number(value: int | None, total: int | None) -> tuple[str | None, str | None]:
    return (
        None if value is None else str(value),
        None if total is None else str(total),
    )


def vorbis_comments(meta: TrackMetadata, gain: ReplayGain) -> dict[str, str]:
    """The Vorbis comments of an Ogg/Opus archive file (empty values left out)."""
    track, tracks = _number(meta.track_number, meta.total_tracks)
    disc, discs = _number(meta.disc_number, meta.total_discs)
    mb = meta.musicbrainz
    pairs: list[tuple[str, str | None]] = [
        ("TITLE", meta.title),
        ("ARTIST", meta.artist),
        ("ARTISTSORT", meta.artist_sort),
        ("ALBUMARTIST", meta.album_artist),
        ("ALBUM", meta.album),
        ("TRACKNUMBER", track),
        ("TRACKTOTAL", tracks),
        ("DISCNUMBER", disc),
        ("DISCTOTAL", discs),
        ("DATE", None if meta.year is None else str(meta.year)),
        ("GENRE", meta.genre),
        ("RELEASETYPE", meta.release_type),
        ("ISRC", meta.isrc),
        ("MUSICBRAINZ_TRACKID", mb.recording_id),
        ("MUSICBRAINZ_RELEASETRACKID", mb.track_id),
        ("MUSICBRAINZ_ALBUMID", mb.release_id),
        ("MUSICBRAINZ_RELEASEGROUPID", mb.release_group_id),
        ("MUSICBRAINZ_ARTISTID", mb.artist_id),
        ("MUSICBRAINZ_ALBUMARTISTID", mb.album_artist_id),
    ]
    pairs += [(key.upper(), value) for key, value in _gain_pairs(gain)]
    pairs += _r128_pairs(gain)
    return {key: _clean(value) for key, value in pairs if value}


def _r128_pairs(gain: ReplayGain) -> list[tuple[str, str | None]]:
    album = None if gain.album_gain_db is None else _r128(gain.album_gain_db)
    return [("R128_TRACK_GAIN", _r128(gain.track_gain_db)), ("R128_ALBUM_GAIN", album)]


def mp4_atoms(meta: TrackMetadata, gain: ReplayGain) -> dict[str, list[object]]:
    """The iTunes atoms of an M4A archive file (empty values left out)."""
    atoms: dict[str, list[object]] = {}
    text: list[tuple[str, str | None]] = [
        ("\xa9nam", meta.title),
        ("\xa9ART", meta.artist),
        ("soar", meta.artist_sort),
        ("aART", meta.album_artist),
        ("\xa9alb", meta.album),
        ("\xa9day", None if meta.year is None else str(meta.year)),
        ("\xa9gen", meta.genre),
    ]
    for key, value in text:
        if value:
            atoms[key] = [_clean(value)]
    if meta.track_number is not None:
        atoms["trkn"] = [(meta.track_number, meta.total_tracks or 0)]
    if meta.disc_number is not None:
        atoms["disk"] = [(meta.disc_number, meta.total_discs or 0)]
    mb = meta.musicbrainz
    free: list[tuple[str, str | None]] = [
        ("ISRC", meta.isrc),
        ("MusicBrainz Album Type", meta.release_type),
        ("MusicBrainz Track Id", mb.recording_id),
        ("MusicBrainz Release Track Id", mb.track_id),
        ("MusicBrainz Album Id", mb.release_id),
        ("MusicBrainz Release Group Id", mb.release_group_id),
        ("MusicBrainz Artist Id", mb.artist_id),
        ("MusicBrainz Album Artist Id", mb.album_artist_id),
        *_gain_pairs(gain),
    ]
    atoms.update(_freeform(free))
    return atoms


def _freeform(pairs: Iterable[tuple[str, str | None]]) -> dict[str, list[object]]:
    return {
        f"{_ITUNES}{name}": [_freeform_value(_clean(value).encode("utf-8"))]
        for name, value in pairs
        if value
    }


def write_tags(path: Path, kind: ArchiveKind, meta: TrackMetadata, gain: ReplayGain) -> None:
    """Replaces every tag of the archive file at `path`."""
    try:
        if kind == OPUS:
            opus = _open_opus(path)
            opus.delete()
            for key, value in vorbis_comments(meta, gain).items():
                opus[key] = [value]
            opus.save()
        elif kind == M4A:
            mp4 = _open_mp4(path)
            if mp4.tags is None:
                mp4.add_tags()
            mp4.tags.clear()
            mp4.update(mp4_atoms(meta, gain))
            mp4.save()
        else:
            raise TaggingError(f"cannot tag {kind.format}")
    except MutagenError as exc:
        raise TaggingError(f"cannot tag {path.name}: {exc}") from exc


def write_replay_gain(path: Path, kind: ArchiveKind, gain: ReplayGain) -> None:
    """Rewrites only the ReplayGain tags (album gain once the album is complete)."""
    try:
        if kind == OPUS:
            opus = _open_opus(path)
            for key, value in [*_gain_pairs(gain), *_r128_pairs(gain)]:
                if value is None:
                    opus.pop(key.upper(), None)
                else:
                    opus[key.upper()] = [value]
            opus.save()
        elif kind == M4A:
            mp4 = _open_mp4(path)
            if mp4.tags is None:
                mp4.add_tags()
            for name, value in _gain_pairs(gain):
                if value is None:
                    mp4.pop(f"{_ITUNES}{name}", None)
            mp4.update(_freeform(_gain_pairs(gain)))
            mp4.save()
        else:
            raise TaggingError(f"cannot tag {kind.format}")
    except MutagenError as exc:
        raise TaggingError(f"cannot tag {path.name}: {exc}") from exc


def _parse_gain(values: list[str]) -> float | None:
    for value in values:
        match = _GAIN.match(value)
        if match:
            return float(match.group(1))
    return None


def _parse_peak(values: list[str]) -> float | None:
    for value in values:
        try:
            peak = float(value)
        except ValueError:
            continue
        if peak >= 0:
            return peak
    return None


def read_track_gain(path: Path, kind: ArchiveKind) -> ReplayGain | None:
    """The track ReplayGain stored in the file, or None when missing or unreadable."""
    try:
        if kind == OPUS:
            opus = _open_opus(path)
            gains = list(opus.get("REPLAYGAIN_TRACK_GAIN", []))
            peaks = list(opus.get("REPLAYGAIN_TRACK_PEAK", []))
        elif kind == M4A:
            mp4 = _open_mp4(path)
            gains = _texts(mp4.get(f"{_ITUNES}replaygain_track_gain", []))
            peaks = _texts(mp4.get(f"{_ITUNES}replaygain_track_peak", []))
        else:
            return None
    except MutagenError:
        return None
    gain, peak = _parse_gain(gains), _parse_peak(peaks)
    if gain is None or peak is None:
        return None
    return ReplayGain(gain, peak)


def _texts(values: Iterable[object]) -> list[str]:
    return [v.decode("utf-8", errors="replace") for v in values if isinstance(v, bytes)]
