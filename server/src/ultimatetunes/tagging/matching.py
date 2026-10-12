# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Choosing the MusicBrainz recording (and release) that matches a YouTube Music track.

Score in [0, 1] = 0.45 x title similarity + 0.35 x artist similarity + 0.20 x duration
agreement. Similarities compare casefolded, NFKC-normalized text with punctuation removed,
with and without bracketed parts ("(Live)", "[Remastered]", "(feat. X)"), keeping the better
one. Duration: 1 within 2 s, falling linearly to 0 at 10 s; 0.5 when either side is unknown.
A score below `TaggingSettings.musicbrainz_min_score` is a weak match: the YouTube Music
data is kept and the track is marked `needs_review` (RF-04).

Among the releases of the chosen recording, the one whose title is closest to the YouTube
Music album wins; ties go to official releases, then to the earliest date.
"""

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from ultimatetunes.tagging.model import MusicBrainzIds, TrackMetadata

TITLE_WEIGHT = 0.45
ARTIST_WEIGHT = 0.35
DURATION_WEIGHT = 0.20
DURATION_EXACT_MS = 2000
DURATION_OFF_MS = 10000
_BRACKETS = re.compile(r"\([^)]*\)|\[[^\]]*\]|\{[^}]*\}")
_PUNCT = re.compile(r"[^\w\s]")
_MBID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_ISRC = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}\d{7}$")
_YEAR = re.compile(r"^(\d{4})")
MAX_TEXT = 500


@dataclass(frozen=True)
class Query:
    """What YouTube Music told us about the track (the job hints)."""

    title: str
    artist: str
    album: str | None
    duration_ms: int | None


def normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(_PUNCT.sub(" ", folded).split())


def similarity(left: str, right: str) -> float:
    """Best ratio of the two texts, with and without bracketed parts."""
    best = 0.0
    for a, b in ((left, right), (_BRACKETS.sub(" ", left), _BRACKETS.sub(" ", right))):
        na, nb = normalize(a), normalize(b)
        if na and nb:
            best = max(best, SequenceMatcher(None, na, nb).ratio())
    return best


def duration_agreement(left_ms: int | None, right_ms: int | None) -> float:
    if left_ms is None or right_ms is None:
        return 0.5
    diff = abs(left_ms - right_ms)
    if diff <= DURATION_EXACT_MS:
        return 1.0
    return max(0.0, 1.0 - (diff - DURATION_EXACT_MS) / (DURATION_OFF_MS - DURATION_EXACT_MS))


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    clean = value.replace("\x00", "").strip()
    return clean[:MAX_TEXT] or None


def _mbid(value: Any) -> str | None:
    return value if isinstance(value, str) and _MBID.fullmatch(value) else None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _positive(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    return value if isinstance(value, int) and 0 < value < 10000 else None  # noqa: PLR2004


def credit_name(artist_credit: Any) -> str | None:
    """The artist credit as printed: names joined by their join phrases."""
    parts = []
    for credit in _list(artist_credit):
        name = _text(credit.get("name")) or _text(_dict(credit.get("artist")).get("name"))
        if name is None:
            return None
        parts.append(name + (credit.get("joinphrase") or ""))
    return _text("".join(parts))


def _first_artist(artist_credit: Any) -> dict[str, Any]:
    found = _list(artist_credit)
    return _dict(found[0].get("artist")) if found else {}


def score(query: Query, recording: dict[str, Any]) -> float:
    title = _text(recording.get("title")) or ""
    artist = credit_name(recording.get("artist-credit")) or ""
    length = recording.get("length")
    total = (
        TITLE_WEIGHT * similarity(query.title, title)
        + ARTIST_WEIGHT * similarity(query.artist, artist)
        + DURATION_WEIGHT
        * duration_agreement(query.duration_ms, length if isinstance(length, int) else None)
    )
    return round(total, 4)


def _release_key(query: Query, release: dict[str, Any]) -> tuple[float, int, str]:
    """Smallest first: closest album title, then official, then earliest date."""
    album = _text(release.get("title")) or ""
    album_score = similarity(query.album, album) if query.album else 0.0
    official = 0 if release.get("status") == "Official" else 1
    return (-round(album_score, 4), official, _text(release.get("date")) or "9999")


def best_release(query: Query, recording: dict[str, Any]) -> dict[str, Any] | None:
    releases = _list(recording.get("releases"))
    return min(releases, key=lambda release: _release_key(query, release)) if releases else None


@dataclass(frozen=True)
class Candidate:
    score: float
    recording: dict[str, Any]


def best_candidate(query: Query, recordings: list[dict[str, Any]]) -> Candidate | None:
    found = [Candidate(score(query, rec), rec) for rec in _list(recordings)]
    return max(found, key=lambda c: c.score) if found else None


def _year(*dates: Any) -> int | None:
    for date in dates:
        match = _YEAR.match(date) if isinstance(date, str) else None
        if match:
            return int(match.group(1))
    return None


def _release_type(release: dict[str, Any]) -> str | None:
    group = _dict(release.get("release-group"))
    secondary = group.get("secondary-types")
    if isinstance(secondary, list) and secondary and isinstance(secondary[0], str):
        return _text(secondary[0].lower())
    primary = group.get("primary-type")
    return _text(primary.lower()) if isinstance(primary, str) else None


def _genre(recording: dict[str, Any]) -> str | None:
    tags = [t for t in _list(recording.get("tags")) if isinstance(t.get("count"), int)]
    if not tags:
        return None
    top = max(tags, key=lambda t: int(t["count"]))
    name = _text(top.get("name"))
    return name.title() if name else None


def _isrc(recording: dict[str, Any]) -> str | None:
    isrcs = recording.get("isrcs")
    if isinstance(isrcs, list):
        for isrc in isrcs:
            if isinstance(isrc, str) and _ISRC.fullmatch(isrc):
                return isrc
    return None


def _medium(release: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    media = _list(release.get("media"))
    medium = media[0] if media else {}
    tracks = _list(medium.get("track"))
    return medium, (tracks[0] if tracks else {})


@dataclass(frozen=True)
class YoutubeIds:
    """The YouTube Music fields kept whatever the match (and used when it is weak)."""

    album_browse_id: str | None = None
    artist_channel_id: str | None = None
    track_number: int | None = None
    year: int | None = None


def from_youtube(query: Query, hints: YoutubeIds, *, match_score: float | None) -> TrackMetadata:
    """Weak or no match: the YouTube Music data, marked `needs_review`. A single without an
    album is filed under its own title (as YouTube Music does)."""
    return TrackMetadata(
        title=query.title,
        artist=query.artist,
        album_artist=query.artist,
        album=query.album or query.title,
        track_number=hints.track_number,
        year=hints.year,
        album_browse_id=hints.album_browse_id,
        artist_channel_id=hints.artist_channel_id,
        needs_review=True,
        match_score=match_score,
    )


def from_musicbrainz(query: Query, hints: YoutubeIds, candidate: Candidate) -> TrackMetadata:
    """A strong match: MusicBrainz data, YouTube Music fields where MusicBrainz has none."""
    recording = candidate.recording
    release = best_release(query, recording) or {}
    medium, track = _medium(release)
    artist_credit = recording.get("artist-credit")
    artist = credit_name(artist_credit) or query.artist
    single_artist = len(_list(artist_credit)) == 1
    first = _first_artist(artist_credit)
    release_artist_credit = release.get("artist-credit")
    album_artist = credit_name(release_artist_credit) or artist
    album_first = _first_artist(release_artist_credit) if release_artist_credit else first
    return TrackMetadata(
        title=_text(recording.get("title")) or query.title,
        artist=artist,
        artist_sort=_text(first.get("sort-name")) if single_artist else None,
        album_artist=album_artist,
        album=_text(release.get("title")) or query.album or query.title,
        track_number=_positive(track.get("number")) or _positive(track.get("position")),
        disc_number=_positive(medium.get("position")),
        total_tracks=_positive(medium.get("track-count")),
        total_discs=None,
        year=_year(release.get("date"), recording.get("first-release-date")) or hints.year,
        genre=_genre(recording),
        release_type=_release_type(release),
        isrc=_isrc(recording),
        musicbrainz=MusicBrainzIds(
            recording_id=_mbid(recording.get("id")),
            track_id=_mbid(track.get("id")),
            release_id=_mbid(release.get("id")),
            release_group_id=_mbid(_dict(release.get("release-group")).get("id")),
            artist_id=_mbid(first.get("id")),
            album_artist_id=_mbid(album_first.get("id")),
        ),
        album_browse_id=hints.album_browse_id,
        artist_channel_id=hints.artist_channel_id,
        needs_review=False,
        match_score=candidate.score,
    )
