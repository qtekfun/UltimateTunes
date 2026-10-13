# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Charts and moods (RF-06): public YouTube Music lists, local-first, no new host.

`get_charts(country)` and `get_mood_categories()`/`get_mood_playlists()` of `ytmusicapi`
(already-approved host) answer the owner's "from public platform lists" ask without contacting
anything new. The chart/mood songs are mapped **local-first** exactly like radio: a video
already archived becomes the library song (with the caller's own stars and play counts); a
`pending`/`failed` one keeps its `yt:` id and `libraryState`. Nothing is materialised.

`map_local_first` is the shared mapping used here and by the external sources
(`radio/external.py`): catalog tracks → `Song`s, archived videos resolved to their library
songs, songs too long to ever download dropped unless already archived, duplicates and a
`blocked` set removed.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from starlette.concurrency import run_in_threadpool

from ultimatetunes.core.limits import DownloadLimits
from ultimatetunes.db.database import Database
from ultimatetunes.db.driver import Connection
from ultimatetunes.errors import FeatureDisabled
from ultimatetunes.ids.resolve import tracks_for_videos
from ultimatetunes.ids.virtual import song_id
from ultimatetunes.radio.service import _song, radio_settings
from ultimatetunes.radio.settings import RadioSettings
from ultimatetunes.search.catalog import CatalogTrack, MoodCategory, MusicCatalog
from ultimatetunes.search.library import LibrarySearch
from ultimatetunes.search.service import Song

if TYPE_CHECKING:
    from ultimatetunes.core.services import Services

# Largest chart/mood list a client can ask for.
MAX_ITEMS = 100


def map_local_first(
    conn: Connection,
    tracks: Sequence[CatalogTrack],
    *,
    user_id: str,
    limits: DownloadLimits,
    blocked: frozenset[str] = frozenset(),
) -> list[Song]:
    """Catalog tracks → `Song`s, local-first, deduplicated, `blocked` ids and too-long
    non-archived songs left out. Order is preserved."""
    refs = tracks_for_videos(conn, [t.video_id for t in tracks])
    ready = [r.id for r in refs.values() if r.status == "ready"]
    library = {s.id: s for s in LibrarySearch(conn).songs_by_id(user_id, ready)}
    out: list[Song] = []
    seen: set[str] = set()
    for track in tracks:
        ref = refs.get(track.video_id)
        archived = ref is not None and ref.status == "ready"
        if not archived and limits.too_long(track.duration_s):
            continue
        key = ref.id if ref is not None else song_id(track.video_id)
        if key in blocked or key in seen:
            continue
        seen.add(key)
        out.append(_song(track, ref, library))
    return out


@dataclass(frozen=True)
class Charts:
    country: str
    items: Sequence[Song]


class ChartsService:
    def __init__(
        self,
        db: Database,
        catalog: MusicCatalog,
        settings: RadioSettings,
        limits: DownloadLimits | None = None,
    ) -> None:
        self._db = db
        self._catalog = catalog
        self._settings = settings
        self._limits = limits or DownloadLimits()

    @classmethod
    def of(cls, services: "Services") -> "ChartsService":
        return cls(services.db, services.catalog, radio_settings())

    def _require_enabled(self) -> None:
        if not self._settings.radio or not self._settings.charts:
            raise FeatureDisabled("Charts are switched off")

    async def charts(self, user_id: str, country: str | None, limit: int) -> Charts:
        self._require_enabled()
        where = country or self._settings.charts_country
        tracks = await self._catalog.charts(where)
        songs = await run_in_threadpool(self._map, user_id, tracks, limit)
        return Charts(where, songs)

    async def moods(self) -> list[MoodCategory]:
        self._require_enabled()
        return await self._catalog.moods()

    async def mood_tracks(self, user_id: str, params: str, limit: int) -> Sequence[Song]:
        self._require_enabled()
        tracks = await self._catalog.mood_tracks(params)
        return await run_in_threadpool(self._map, user_id, tracks, limit)

    def _map(self, user_id: str, tracks: Sequence[CatalogTrack], limit: int) -> list[Song]:
        with self._db.read() as conn:
            return map_local_first(conn, tracks, user_id=user_id, limits=self._limits)[:limit]
