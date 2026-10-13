# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""External recommendation sources (RF-06), server-side, each **off by default**.

The owner confirmed the architecture: the Android app only ever talks to the user's server;
the **server** is the one that fetches the external info. Each source is a per-server setting
the owner opts into. A source looks up **public, anonymous** data (never the caller's listening
history) and turns it into seed tracks that are matched on YouTube Music and mapped local-first,
so the shelves render with the same `TrackItem`s as everything else. On any failure a source
yields no shelf and the rest of `/ut/v1/recommendations` is still returned.

Wired now:
- **ListenBrainz** (`api.listenbrainz.org`, CC0, read-only): for each of the caller's
  favourite/most-played artists that has a MusicBrainz id, the artist's community-popular
  recordings, matched on YouTube Music. Only a public artist id is sent, never any history.

Documented but **not** wired (see `docs/recommendations.md`): SomaFM (its ToS forbids
third-party apps and automated re-posting of its playlists), Radio Paradise (no public API
terms permitting reuse), and a generic admin-configurable station feed (proposed design).
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from starlette.concurrency import run_in_threadpool

from ultimatetunes.core.limits import DownloadLimits
from ultimatetunes.core.ratelimit import RateLimiter
from ultimatetunes.db.database import Database
from ultimatetunes.db.repository import Repository
from ultimatetunes.errors import TunesError
from ultimatetunes.radio.discovery import map_local_first
from ultimatetunes.radio.listenbrainz import ListenBrainz, ListenBrainzError, default_client
from ultimatetunes.radio.settings import RadioSettings
from ultimatetunes.search.catalog import CatalogTrack, MusicCatalog
from ultimatetunes.search.service import Song

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceShelf:
    """One external-source shelf: a title and local-first songs. `source` names the origin."""

    source: str
    title: str
    items: Sequence[Song]


class RecommendationSource(Protocol):
    source: str

    async def shelves(
        self, user_id: str, limit: int, blocked: frozenset[str]
    ) -> list[SourceShelf]: ...


@dataclass(frozen=True)
class _ArtistSeed:
    name: str
    mbid: str


# The caller's favourite/most-played artists that carry a MusicBrainz id, best first. Portable
# SQL (SQLite + PostgreSQL): COALESCE/SUM/MAX/CASE and a GROUP BY only.
_SEED_ARTISTS = (
    "SELECT a.name AS name, a.musicbrainz_id AS mbid, "
    "COALESCE(SUM(s.play_count), 0) AS plays, "
    "MAX(CASE WHEN st.track_id IS NULL THEN 0 ELSE 1 END) AS starred "
    "FROM artists a JOIN tracks t ON t.artist_id = a.id "
    "LEFT JOIN user_track_stats s ON s.user_id = ? AND s.track_id = t.id "
    "LEFT JOIN starred_tracks st ON st.user_id = ? AND st.track_id = t.id "
    "WHERE a.musicbrainz_id IS NOT NULL AND t.id IN ("
    "SELECT track_id FROM user_track_stats WHERE user_id = ? AND play_count > 0 "
    "UNION SELECT track_id FROM starred_tracks WHERE user_id = ?) "
    "GROUP BY a.id, a.name, a.musicbrainz_id "
    "ORDER BY plays DESC, starred DESC, a.name "
    "LIMIT ?"
)


@dataclass(frozen=True)
class _SeedRow:
    name: str
    mbid: str
    plays: int
    starred: int


class _SeedRepository(Repository):
    def seed_artists(self, user_id: str, limit: int) -> list[_ArtistSeed]:
        rows = self.all(_SeedRow, _SEED_ARTISTS, (user_id, user_id, user_id, user_id, limit))
        return [_ArtistSeed(r.name, r.mbid) for r in rows]


class ListenBrainzSource:
    source = "listenbrainz"

    def __init__(
        self,
        db: Database,
        catalog: MusicCatalog,
        limiter: RateLimiter,
        settings: RadioSettings,
        limits: DownloadLimits | None = None,
    ) -> None:
        self._db = db
        self._catalog = catalog
        self._limiter = limiter
        self._settings = settings
        self._limits = limits or DownloadLimits()

    async def shelves(self, user_id: str, limit: int, blocked: frozenset[str]) -> list[SourceShelf]:
        seeds = await run_in_threadpool(self._seed_artists, user_id)
        if not seeds:
            return []
        shelves: list[SourceShelf] = []
        async with default_client(self._settings.listenbrainz_timeout_s) as client:
            lb = ListenBrainz(client, self._limiter)
            for seed in seeds:
                shelf = await self._shelf(lb, user_id, seed, limit, blocked)
                if shelf is not None:
                    shelves.append(shelf)
        return shelves

    def _seed_artists(self, user_id: str) -> list[_ArtistSeed]:
        with self._db.read() as conn:
            return _SeedRepository(conn).seed_artists(user_id, self._settings.listenbrainz_seeds)

    async def _shelf(
        self,
        lb: ListenBrainz,
        user_id: str,
        seed: _ArtistSeed,
        limit: int,
        blocked: frozenset[str],
    ) -> SourceShelf | None:
        try:
            recordings = await lb.top_recordings_for_artist(
                seed.mbid, self._settings.listenbrainz_tracks
            )
        except ListenBrainzError as exc:
            log.warning("ListenBrainz lookup failed, skipping that shelf: %s", exc)
            return None
        tracks = await self._match(recordings)
        songs = await run_in_threadpool(self._map, user_id, tracks, limit, blocked)
        if not songs:
            return None
        return SourceShelf("listenbrainz", f"Popular on ListenBrainz · {seed.name}", songs)

    async def _match(self, recordings: Sequence[object]) -> list[CatalogTrack]:
        """Each ListenBrainz recording matched to its best YouTube Music song (cached search)."""
        found: list[CatalogTrack] = []
        seen: set[str] = set()
        for recording in recordings:
            name = getattr(recording, "recording_name", "")
            artist = getattr(recording, "artist_name", "")
            matches = await self._catalog.search_songs(f"{name} {artist}", 1)
            if matches and matches[0].video_id not in seen:
                seen.add(matches[0].video_id)
                found.append(matches[0])
        return found

    def _map(
        self, user_id: str, tracks: Sequence[CatalogTrack], limit: int, blocked: frozenset[str]
    ) -> list[Song]:
        with self._db.read() as conn:
            return map_local_first(
                conn, tracks, user_id=user_id, limits=self._limits, blocked=blocked
            )[:limit]


def build_sources(
    db: Database,
    catalog: MusicCatalog,
    limiter: RateLimiter,
    settings: RadioSettings,
    limits: DownloadLimits | None = None,
) -> list[RecommendationSource]:
    """The external sources the admin switched on (each off by default)."""
    sources: list[RecommendationSource] = []
    if settings.listenbrainz_recommendations:
        sources.append(ListenBrainzSource(db, catalog, limiter, settings, limits))
    return sources


async def gather_shelves(
    sources: Sequence[RecommendationSource],
    user_id: str,
    limit: int,
    blocked: frozenset[str],
) -> list[SourceShelf]:
    """Every source's shelves; a source that raises a `TunesError` (e.g. the catalog is
    rate-limited or unavailable) is skipped so the local/YouTube recommendations still return."""
    out: list[SourceShelf] = []
    for source in sources:
        try:
            out.extend(await source.shelves(user_id, limit, blocked))
        except TunesError as exc:
            log.info("external recommendation source %s unavailable: %s", source.source, exc)
    return out
