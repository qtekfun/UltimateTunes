# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Recommendations (RF-06): new songs to discover, built from what the caller already plays.

The safe, no-new-host baseline of `docs/recommendations.md`. Seeds are the caller's own top
played songs (`user_track_stats`) and favourites (`starred_tracks`), already in the database;
each seed starts the **existing** YouTube Music watch playlist (`MusicCatalog.radio`, the same
call behind `/ut/v1/radio` and `getSimilarSongs2`), so nothing new is contacted. The seed songs
themselves and the songs the caller already plays are dropped, so the shelves surface genuinely
new music. Everything is mapped local-first exactly like radio: an archived video becomes the
library song (with the caller's own stars and play counts); a `pending`/`failed` one keeps its
`yt:` id and `libraryState`. Nothing is materialized — listing recommendations is not a "keep".

Shelves (`Recommendations`):
- `recommended_for_you`: the songs that the most seed radios agree on, ranked by that agreement
  then by their order in the radios;
- `because_you_played`: one shelf per seed (the seed song and the new songs of its radio).

Both hit YouTube Music, so this is a separate endpoint from `/ut/v1/listen-now` (library only).
The catalog calls go through the shared cache and the caller's rate-limit bucket, like radio.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from starlette.concurrency import run_in_threadpool

from ultimatetunes.core.limits import DownloadLimits
from ultimatetunes.db.database import Database
from ultimatetunes.db.repository import Repository
from ultimatetunes.errors import FeatureDisabled
from ultimatetunes.ids.resolve import TrackRef, tracks_for_videos
from ultimatetunes.ids.virtual import SONG_PREFIX, song_id
from ultimatetunes.radio.external import (
    RecommendationSource,
    SourceShelf,
    build_sources,
    gather_shelves,
)
from ultimatetunes.radio.service import _song, radio_settings
from ultimatetunes.radio.settings import RadioSettings
from ultimatetunes.search.catalog import CatalogTrack, MusicCatalog
from ultimatetunes.search.library import LibrarySearch, LibrarySong
from ultimatetunes.search.service import Song

if TYPE_CHECKING:
    from ultimatetunes.core.services import Services

# Largest shelf (and aggregated list) a client can ask for.
MAX_ITEMS = 50
# Songs fetched from a seed's radio on top of `limit`, so there is room to drop the seed's own
# video, the other seeds' videos and songs the caller already plays and still fill the shelf. A
# shelf may still be shorter than `limit` when a radio runs out of new songs after those drops.
OVERFETCH = 10


@dataclass(frozen=True)
class Shelf:
    """One "Because you played …" shelf: the seed song and the new songs of its radio."""

    seed: Song
    items: Sequence[Song]


@dataclass(frozen=True)
class Recommendations:
    recommended_for_you: Sequence[Song]
    because_you_played: Sequence[Shelf]
    # Shelves from external sources the admin switched on (ListenBrainz, ...), each off by
    # default; empty when no source is on or every source degraded.
    shelves: Sequence[SourceShelf] = ()


@dataclass(frozen=True)
class _SeedRow:
    track_id: str
    yt_video_id: str | None
    first_alias: str | None
    play_count: int
    starred: int
    touched_at: str | None


@dataclass(frozen=True)
class _Seed:
    track_id: str
    video_id: str


@dataclass(frozen=True)
class _PlayedId:
    track_id: str


# Candidate seeds: the caller's played and favourite songs, best first. The alias is the oldest
# `yt:` id of a song that has no `yt_video_id` of its own (e.g. a song archived from one video
# but aliased to others), so a library song that never stored a video can still seed a radio.
_SEEDS = (
    "SELECT t.id AS track_id, t.yt_video_id, "
    "(SELECT a.alias FROM track_aliases a WHERE a.track_id = t.id"
    " ORDER BY a.created_at, a.alias LIMIT 1) AS first_alias, "
    "COALESCE(s.play_count, 0) AS play_count, "
    "CASE WHEN st.track_id IS NULL THEN 0 ELSE 1 END AS starred, "
    "COALESCE(s.last_played_at, st.starred_at) AS touched_at "
    "FROM tracks t "
    "LEFT JOIN user_track_stats s ON s.user_id = ? AND s.track_id = t.id "
    "LEFT JOIN starred_tracks st ON st.user_id = ? AND st.track_id = t.id "
    "WHERE t.status IN ('ready', 'pending', 'failed') AND t.id IN ("
    "SELECT track_id FROM user_track_stats WHERE user_id = ? AND play_count > 0 "
    "UNION SELECT track_id FROM starred_tracks WHERE user_id = ?) "
    "ORDER BY play_count DESC, starred DESC, touched_at DESC, t.id "
    "LIMIT ?"
)
# Songs the caller already plays: never recommended back to them (archived ids only).
_PLAYED = "SELECT track_id FROM user_track_stats WHERE user_id = ? AND play_count > 0"


class RecommendationsRepository(Repository):
    def seed_rows(self, user_id: str, limit: int) -> list[_SeedRow]:
        return self.all(_SeedRow, _SEEDS, (user_id, user_id, user_id, user_id, limit))

    def played_ids(self, user_id: str) -> set[str]:
        return {r.track_id for r in self.all(_PlayedId, _PLAYED, (user_id,))}


def _video_of(row: _SeedRow) -> str | None:
    if row.yt_video_id is not None:
        return row.yt_video_id
    if row.first_alias is not None:
        return row.first_alias.removeprefix(SONG_PREFIX)
    return None


class RecommendationsService:
    def __init__(
        self,
        db: Database,
        catalog: MusicCatalog,
        settings: RadioSettings,
        limits: DownloadLimits | None = None,
        sources: Sequence[RecommendationSource] | None = None,
    ) -> None:
        self._db = db
        self._catalog = catalog
        self._settings = settings
        self._limits = limits or DownloadLimits()
        self._sources = list(sources) if sources is not None else []

    @classmethod
    def of(cls, services: "Services") -> "RecommendationsService":
        settings = radio_settings()
        sources = build_sources(services.db, services.catalog, services.rate_limiter, settings)
        return cls(services.db, services.catalog, settings, sources=sources)

    async def recommend(self, user_id: str, limit: int) -> Recommendations:
        """`recommended_for_you`, up to `recommendation_seeds` "because you played" shelves, and
        the external-source shelves (ListenBrainz, ...), each of at most `limit` songs.

        Empty (and no catalog call) when the caller has no plays or favourites to seed from and
        no external source is on.
        """
        if not self._settings.radio or not self._settings.recommendations:
            raise FeatureDisabled("Recommendations are switched off")
        seeds = await run_in_threadpool(self._pick_seeds, user_id)
        if not seeds:
            shelves = await self._external_shelves(user_id, limit, frozenset())
            return Recommendations([], [], shelves)
        window = min(MAX_ITEMS + OVERFETCH, limit + OVERFETCH)
        radios: list[tuple[_Seed, list[CatalogTrack]]] = []
        for seed in seeds:
            tracks = await self._catalog.radio(seed.video_id, window)
            radios.append((seed, tracks))
        local = await run_in_threadpool(self._build, user_id, radios, limit)
        blocked = await run_in_threadpool(self._blocked, user_id, {s.track_id for s in seeds})
        shelves = await self._external_shelves(user_id, limit, blocked)
        return Recommendations(local.recommended_for_you, local.because_you_played, shelves)

    async def _external_shelves(
        self, user_id: str, limit: int, blocked: frozenset[str]
    ) -> list[SourceShelf]:
        if not self._sources:
            return []
        return await gather_shelves(self._sources, user_id, limit, blocked)

    def _blocked(self, user_id: str, seed_tracks: set[str]) -> frozenset[str]:
        """The caller's own rotation (seed songs and anything played): never recommended back,
        including by an external source."""
        with self._db.read() as conn:
            played = RecommendationsRepository(conn).played_ids(user_id)
        return frozenset(seed_tracks | played)

    # ------------------------------------------------------------------ seeds

    def _pick_seeds(self, user_id: str) -> list[_Seed]:
        """The best seeds that resolve to a video, deduplicated by video, best first."""
        want = self._settings.recommendation_seeds
        with self._db.read() as conn:
            # Read a few more than needed: some rows may not resolve to a video.
            rows = RecommendationsRepository(conn).seed_rows(user_id, want * 3)
        seeds: list[_Seed] = []
        seen: set[str] = set()
        for row in rows:
            video = _video_of(row)
            if video is None or video in seen:
                continue
            seen.add(video)
            seeds.append(_Seed(row.track_id, video))
            if len(seeds) >= want:
                break
        return seeds

    # ------------------------------------------------------------------ build

    def _build(
        self, user_id: str, radios: list[tuple[_Seed, list[CatalogTrack]]], limit: int
    ) -> Recommendations:
        seed_videos = {seed.video_id for seed, _ in radios}
        seed_tracks = {seed.track_id for seed, _ in radios}
        every_video = [t.video_id for _, tracks in radios for t in tracks]
        with self._db.read() as conn:
            refs = tracks_for_videos(conn, every_video)
            ready = [r.id for r in refs.values() if r.status == "ready"]
            library = {s.id: s for s in LibrarySearch(conn).songs_by_id(user_id, ready)}
            played = RecommendationsRepository(conn).played_ids(user_id)
        # The caller's own rotation is never recommended back: seed songs and anything played.
        blocked = seed_tracks | played
        shelves: list[Shelf] = []
        # key -> (song, agreement count, first position) for the aggregated shelf.
        order = 0
        agg: dict[str, tuple[Song, int, int]] = {}
        for seed, tracks in radios:
            seed_track = next((t for t in tracks if t.video_id == seed.video_id), tracks[0])
            seed_song = _song(seed_track, refs.get(seed.video_id), library)
            items: list[Song] = []
            seen: set[str] = set()
            for track in tracks:
                if len(items) >= limit:
                    break
                candidate = self._candidate(track, refs, library, blocked, seed_videos)
                if candidate is None:
                    continue
                key, song = candidate
                if key in seen:
                    continue
                seen.add(key)
                items.append(song)
                existing = agg.get(key)
                if existing is None:
                    agg[key] = (song, 1, order)
                    order += 1
                else:
                    agg[key] = (existing[0], existing[1] + 1, existing[2])
            if items:
                shelves.append(Shelf(seed_song, items))
        ranked = sorted(agg.values(), key=lambda v: (-v[1], v[2]))
        recommended = [song for song, _count, _order in ranked[:limit]]
        return Recommendations(recommended, shelves)

    def _candidate(
        self,
        track: CatalogTrack,
        refs: dict[str, TrackRef],
        library: dict[str, LibrarySong],
        blocked: set[str],
        seed_videos: set[str],
    ) -> tuple[str, Song] | None:
        if track.video_id in seed_videos:
            return None
        ref = refs.get(track.video_id)
        archived = ref is not None and ref.status == "ready"
        if not archived and self._limits.too_long(track.duration_s):
            return None
        key = ref.id if ref is not None else song_id(track.video_id)
        if key in blocked:
            return None
        return key, _song(track, ref, library)
