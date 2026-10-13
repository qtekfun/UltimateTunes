# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""External recommendation sources: ListenBrainz (respx), seed artists, graceful degrade."""

from collections.abc import Iterator

import pytest
import respx

from tests.search.conftest import LANTERNS, LIGHTHOUSE, USER
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.db import Database
from ultimatetunes.radio.external import (
    ListenBrainzSource,
    SourceShelf,
    build_sources,
    gather_shelves,
)
from ultimatetunes.radio.listenbrainz import TOP_RECORDINGS_URL
from ultimatetunes.radio.settings import RadioSettings
from ultimatetunes.search.catalog import CatalogTrack
from ultimatetunes.search.fake import FakeMusicCatalog
from ultimatetunes.search.library import LibrarySong
from ultimatetunes.search.service import ExternalSong, Song
from ultimatetunes.tagging.ratelimit import MemoryRateLimiter

pytestmark = pytest.mark.anyio
MBID = "11111111-1111-4111-8111-111111111111"
URL = TOP_RECORDINGS_URL.format(artist_mbid=MBID)
RECORDINGS = [
    {"recording_name": "Paper Moons", "artist_name": "The Paper Lanterns"},
    {"recording_name": "Night Ferry", "artist_name": "The Paper Lanterns"},
]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def web() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as router:
        yield router


class StubCatalog(FakeMusicCatalog):
    """The fake catalog, but `search_songs` resolves a whole query to one preset video id."""

    def __init__(self, search_map: dict[str, str]) -> None:
        super().__init__()
        self.search_map = search_map
        self.queries: list[str] = []

    async def search_songs(self, query: str, limit: int) -> list[CatalogTrack]:
        self.queries.append(query)
        video = self.search_map.get(query)
        return [self.tracks[video]] if video else []


def key(song: Song) -> str:
    if isinstance(song, ExternalSong):
        return f"yt:{song.track.video_id}"
    return song.id


def _with_mbid(library: Database) -> None:
    with library.transaction() as conn:
        conn.execute("UPDATE artists SET musicbrainz_id = ? WHERE id = ?", (MBID, LANTERNS))


def _source(
    library: Database, catalog: FakeMusicCatalog, settings: RadioSettings | None = None
) -> ListenBrainzSource:
    limiter = MemoryRateLimiter(FakeClock())
    return ListenBrainzSource(library, catalog, limiter, settings or RadioSettings())


async def test_shelf_matches_recordings_local_first_and_respects_blocked(
    library: Database, web: respx.MockRouter
) -> None:
    _with_mbid(library)
    web.get(URL).respond(200, json=RECORDINGS)
    catalog = StubCatalog(
        {
            "Paper Moons The Paper Lanterns": "Qx7Lm2pZ0aB",  # external, kept
            "Night Ferry The Paper Lanterns": "Wq5Jd7HsKe2",  # alias of Lighthouse Keeper
        }
    )
    source = _source(library, catalog, RadioSettings(listenbrainz_tracks=5))
    # Lighthouse Keeper is in the caller's rotation (blocked), so its match is dropped.
    shelves = await source.shelves(USER, 20, frozenset({LIGHTHOUSE}))
    assert len(shelves) == 1
    assert shelves[0].source == "listenbrainz"
    assert shelves[0].title == "Popular on ListenBrainz · The Paper Lanterns"
    assert [key(s) for s in shelves[0].items] == ["yt:Qx7Lm2pZ0aB"]


async def test_a_library_match_becomes_the_library_song(
    library: Database, web: respx.MockRouter
) -> None:
    _with_mbid(library)
    web.get(URL).respond(200, json=[{"recording_name": "Low Tide", "artist_name": "x"}])
    catalog = StubCatalog({"Low Tide x": "Fk2Lp9QwXa1"})  # archived as Low Tide Letters
    shelves = await _source(library, catalog).shelves(USER, 20, frozenset())
    assert isinstance(shelves[0].items[0], LibrarySong)


async def test_no_seed_artists_makes_no_request(library: Database, web: respx.MockRouter) -> None:
    # No artist has a MusicBrainz id, so there is nothing to look up.
    route = web.get(URL).respond(200, json=RECORDINGS)
    catalog = StubCatalog({})
    assert await _source(library, catalog).shelves(USER, 20, frozenset()) == []
    assert not route.called
    assert catalog.queries == []


async def test_a_failing_lookup_is_skipped(library: Database, web: respx.MockRouter) -> None:
    _with_mbid(library)
    web.get(URL).respond(503)
    assert await _source(library, StubCatalog({})).shelves(USER, 20, frozenset()) == []


async def test_a_shelf_with_no_matches_is_dropped(library: Database, web: respx.MockRouter) -> None:
    _with_mbid(library)
    web.get(URL).respond(200, json=RECORDINGS)
    # Nothing matches on YouTube Music.
    assert await _source(library, StubCatalog({})).shelves(USER, 20, frozenset()) == []


async def test_build_sources_follows_the_setting(library: Database) -> None:
    catalog = FakeMusicCatalog()
    limiter = MemoryRateLimiter(FakeClock())
    assert build_sources(library, catalog, limiter, RadioSettings()) == []
    on = build_sources(library, catalog, limiter, RadioSettings(listenbrainz_recommendations=True))
    assert [s.source for s in on] == ["listenbrainz"]


async def test_gather_shelves_skips_a_source_that_raises() -> None:
    class Boom:
        source = "boom"

        async def shelves(
            self, user_id: str, limit: int, blocked: frozenset[str]
        ) -> list[SourceShelf]:
            from ultimatetunes.errors import UpstreamUnavailable  # noqa: PLC0415

            raise UpstreamUnavailable()

    class Ok:
        source = "ok"

        async def shelves(
            self, user_id: str, limit: int, blocked: frozenset[str]
        ) -> list[SourceShelf]:
            return [SourceShelf("ok", "Ok", [])]

    out = await gather_shelves([Boom(), Ok()], "u", 20, frozenset())
    assert [s.source for s in out] == ["ok"]
