# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Matching a source track to a YouTube Music song (RF-08): title, artists, album, duration.

YouTube Music has no ISRC, so matching is on text. `query_for` builds the search ("artist
title"); `best_match` scores each candidate and keeps the best one at or above `THRESHOLD`:

- **title** (weight 0.45): the better `difflib` ratio of the normalised titles, with and
  without decorations (`(feat. …)`, `[Remastered]`, `- Radio Edit`); below 0.6 is no match;
- **artists** (0.30): 1 when a source artist equals a candidate artist (normalised), else the
  word overlap; 0 is no match; neutral 0.5 when the source names none;
- **duration** (0.15): both known and more than `DURATION_TOLERANCE_S` (3 s) apart is no
  match; within it, 1; neutral 0.5 when either is unknown;
- **album** (0.10): equal 1, one containing the other 0.8, else 0; neutral 0.5 when unknown;
- the weighted sum is scaled to 0.98 and an official audio track (`ATV`) gets the last 0.02,
  so it wins a tie against a video of the same song.

An ISRC from the file is only recorded on the item for now (SPEC RF-08: an ISRC resolves the
MusicBrainz recording once that lookup exists, PLAN T09).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

from ultimatetunes.imports.files import SourceItem
from ultimatetunes.search.catalog import CatalogTrack
from ultimatetunes.search.text import normalize

THRESHOLD = 0.7
MIN_TITLE = 0.6
DURATION_TOLERANCE_S = 3
SEARCH_LIMIT = 5
_WEIGHTS = {"title": 0.45, "artist": 0.30, "duration": 0.15, "album": 0.10}
_NEUTRAL = 0.5
_ALBUM_CONTAINS = 0.8
_ATV_BONUS = 0.02
_DECORATIONS = (
    re.compile(r"\s*[\(\[][^\)\]]*[\)\]]"),
    re.compile(r"\s+-\s+.*$"),
    re.compile(r"\s+(?:feat|ft|featuring)\.?\s+.*$", re.IGNORECASE),
)


@dataclass(frozen=True)
class Match:
    track: CatalogTrack
    score: float


def core_title(title: str) -> str:
    """The title without decorations: `Song (feat. X) - Remastered 2011` → `Song`."""
    core = title
    for pattern in _DECORATIONS:
        core = pattern.sub("", core)
    return core.strip() or title


def query_for(item: SourceItem, *, core: bool = False) -> str:
    title = core_title(item.title) if core else item.title
    return " ".join(p for p in (item.artists[0] if item.artists else None, title) if p)


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def title_score(source: str, candidate: str) -> float:
    full = _ratio(normalize(source), normalize(candidate))
    core = _ratio(normalize(core_title(source)), normalize(core_title(candidate)))
    return max(full, core)


def artist_score(source: Sequence[str], candidate: Sequence[str]) -> float:
    if not source:
        return _NEUTRAL
    wanted = {normalize(a) for a in source} - {""}
    have = {normalize(a) for a in candidate} - {""}
    if wanted & have:
        return 1.0
    wanted_words = {w for a in wanted for w in a.split()}
    have_words = {w for a in have for w in a.split()}
    if not wanted_words or not have_words:
        return 0.0
    return len(wanted_words & have_words) / len(wanted_words | have_words)


def album_score(source: str | None, candidate: str | None) -> float:
    if not source or not candidate:
        return _NEUTRAL
    a, b = normalize(source), normalize(candidate)
    if a == b:
        return 1.0
    if a and b and (a in b or b in a):
        return _ALBUM_CONTAINS
    return 0.0


def score(item: SourceItem, candidate: CatalogTrack) -> float | None:
    """The match score in [0, 1], or None when a hard rule excludes the candidate."""
    title = title_score(item.title, candidate.title)
    if title < MIN_TITLE:
        return None
    artist = artist_score(item.artists, [a.name for a in candidate.artists])
    if artist == 0:
        return None
    duration = _NEUTRAL
    if item.duration_s is not None and candidate.duration_s is not None:
        if abs(item.duration_s - candidate.duration_s) > DURATION_TOLERANCE_S:
            return None
        duration = 1.0
    album = album_score(item.album, candidate.album.name if candidate.album else None)
    total = (1 - _ATV_BONUS) * (
        _WEIGHTS["title"] * title
        + _WEIGHTS["artist"] * artist
        + _WEIGHTS["duration"] * duration
        + _WEIGHTS["album"] * album
    )
    if candidate.video_type == "ATV":
        total += _ATV_BONUS
    return round(total, 4)


def best_match(item: SourceItem, candidates: Sequence[CatalogTrack]) -> Match | None:
    """The best candidate at or above `THRESHOLD` (the first one on a tie), else None."""
    best: Match | None = None
    for candidate in candidates:
        value = score(item, candidate)
        if value is None or value < THRESHOLD:
            continue
        if best is None or value > best.score:
            best = Match(candidate, value)
    return best
