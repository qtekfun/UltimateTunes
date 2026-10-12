# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Search merge: library first, external after, deduplicated, never failing on the catalog."""

import asyncio
import logging
from types import SimpleNamespace

import pytest

from tests.search.conftest import (
    BLOOM,
    DUSK,
    HARBOUR_LIGHTS,
    LANTERNS,
    LIGHTHOUSE,
    LOW_TIDE,
    TIDEWATER,
    USER,
)
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.ratelimit import Limit, SqliteRateLimiter
from ultimatetunes.db import Database
from ultimatetunes.search.catalog import (
    CatalogAlbumRef,
    CatalogArtistRef,
    CatalogTrack,
    CatalogUnavailable,
    UnavailableCatalog,
)
from ultimatetunes.search.fake import FakeMusicCatalog
from ultimatetunes.search.library import LibraryAlbum, LibraryArtist, LibrarySearch, LibrarySong
from ultimatetunes.search.service import (
    ExternalSong,
    Page,
    SearchResults,
    SearchService,
    search_settings,
)
from ultimatetunes.search.settings import SearchSettings

pytestmark = pytest.mark.anyio
ALL = Page(20)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def ids(results: SearchResults) -> tuple[list[str], list[str], list[str]]:
    def song(s: LibrarySong | ExternalSong) -> str:
        if isinstance(s, ExternalSong):
            return f"yt:{s.track.video_id}" + (f"[{s.state}]" if s.state else "")
        return s.id

    def album(a: LibraryAlbum | CatalogAlbumRef) -> str:
        return a.id if isinstance(a, LibraryAlbum) else f"ytalbum:{a.browse_id}"

    def artist(a: LibraryArtist | CatalogArtistRef) -> str:
        return a.id if isinstance(a, LibraryArtist) else f"ytartist:{a.channel_id}"

    return (
        [artist(a) for a in results.artists],
        [album(a) for a in results.albums],
        [song(s) for s in results.songs],
    )


async def search(  # noqa: PLR0913 - test knobs
    db: Database,
    query: str,
    catalog: object | None = None,
    settings: SearchSettings | None = None,
    *,
    page: Page = ALL,
    external: bool = True,
) -> SearchResults:
    service = SearchService(db, catalog or FakeMusicCatalog(), settings or SearchSettings())  # type: ignore[arg-type]
    return await service.search(
        USER, query, artists=page, albums=page, songs=page, external=external
    )


async def test_library_first_then_external_deduplicated(library: Database) -> None:
    results = await search(library, "lanterns")
    artists, albums, songs = ids(results)
    # The catalog's artist and Lanterns at Dusk are in the library: shown once.
    assert artists == [LANTERNS]
    assert albums == [HARBOUR_LIGHTS, DUSK]
    # yt:Fk2… is archived (Low Tide Letters), yt:Wq5… aliases Lighthouse Keeper: both dropped.
    assert songs == [
        LIGHTHOUSE,
        LOW_TIDE,
        TIDEWATER,
        "yt:Rb8Tn3ZcYv0[pending]",
        "yt:Qx7Lm2pZ0aB",
    ]
    lighthouse = results.songs[0]
    assert isinstance(lighthouse, LibrarySong)
    assert lighthouse.starred_at is not None
    assert lighthouse.play_count == 14
    assert lighthouse.album_artist_name == "The Paper Lanterns"


async def test_external_hit_archived_in_the_library_becomes_the_library_song(
    library: Database,
) -> None:
    # "ferry" matches nothing in the library, but the catalog's Night Ferry is an alias of
    # Lighthouse Keeper.
    _, _, songs = ids(await search(library, "ferry"))
    assert songs == [LIGHTHOUSE]


async def test_items_known_only_by_their_youtube_ids(library: Database) -> None:
    # Static Bloom and Neon Harbor exist with pending tracks only: still external.
    artists, albums, songs = ids(await search(library, "bloom"))
    assert artists == []
    assert albums == ["ytalbum:MPREb_Hn2Vq8Lr5Tz"]
    assert songs == ["yt:Hm3Vx8Nq2Lp", "yt:Tz9Kd4Wb7Rc[pending]", "yt:Pa6Ye1Uo3Gs"]
    artists, _, _ = ids(await search(library, "neon"))
    assert artists == ["ytartist:UCn4HbR7oQ2sLx9TzV0eWm3K"]
    assert BLOOM not in albums


async def test_library_album_via_youtube_id(library: Database) -> None:
    # "dusk" finds the library album by name and the catalog album by id: once.
    _, albums, _ = ids(await search(library, "dusk"))
    assert albums == [DUSK]


async def test_external_album_resolving_to_a_library_album_outside_the_results(
    library: Database,
) -> None:
    class Renamed(FakeMusicCatalog):
        async def search_albums(self, query: str, limit: int) -> list[CatalogAlbumRef]:
            return [CatalogAlbumRef("MPREb_k3Vd9QmT2xL", "Renamed upstream", ())]

    _, albums, _ = ids(await search(library, "renamed", Renamed()))
    assert albums == [DUSK]


async def test_empty_query_lists_the_library_without_the_catalog(library: Database) -> None:
    catalog = FakeMusicCatalog()
    for query in ("", '""', "   "):
        results = await search(library, query, catalog)
        assert ids(results) == (
            [LANTERNS],
            [HARBOUR_LIGHTS, DUSK],
            [LIGHTHOUSE, LOW_TIDE, TIDEWATER],
        )
    assert catalog.calls == []
    page = await search(library, "", catalog, page=Page(1, 1))
    assert ids(page) == ([], [DUSK], [LOW_TIDE])


async def test_pages_over_merged_results(library: Database) -> None:
    _, _, songs = ids(await search(library, "lanterns", page=Page(2, 2)))
    assert songs == [TIDEWATER, "yt:Rb8Tn3ZcYv0[pending]"]
    _, _, songs = ids(await search(library, "lanterns", page=Page(2, 10**9)))
    assert songs == []


async def test_zero_counts_skip_the_kind(library: Database) -> None:
    catalog = FakeMusicCatalog()
    service = SearchService(library, catalog, SearchSettings())
    results = await service.search(USER, "lanterns", artists=Page(0), albums=Page(0), songs=Page(1))
    assert ids(results) == ([], [], [LIGHTHOUSE])
    assert catalog.calls == ["search_songs"]


async def test_query_without_words_searches_only_the_catalog(library: Database) -> None:
    catalog = FakeMusicCatalog()
    assert ids(await search(library, "!!!", catalog)) == ([], [], [])
    assert sorted(catalog.calls) == ["search_albums", "search_artists", "search_songs"]


async def test_external_can_be_switched_off(library: Database) -> None:
    catalog = FakeMusicCatalog()
    expected = ([LANTERNS], [HARBOUR_LIGHTS, DUSK], [LIGHTHOUSE, LOW_TIDE, TIDEWATER])
    assert ids(await search(library, "lanterns", catalog, external=False)) == expected
    off = SearchSettings(external_search=False)
    assert ids(await search(library, "lanterns", catalog, off)) == expected
    assert catalog.calls == []


async def test_failing_catalog_gives_library_results(
    library: Database, caplog: pytest.LogCaptureFixture
) -> None:
    catalog = FakeMusicCatalog()
    catalog.fail_with = CatalogUnavailable()
    _, _, songs = ids(await search(library, "lanterns", catalog))
    assert songs == [LIGHTHOUSE, LOW_TIDE, TIDEWATER]
    _, _, songs = ids(await search(library, "lanterns", UnavailableCatalog()))
    assert songs == [LIGHTHOUSE, LOW_TIDE, TIDEWATER]

    class Broken(FakeMusicCatalog):
        async def search_songs(self, query: str, limit: int) -> list[CatalogTrack]:
            raise RuntimeError("bug")

    with caplog.at_level(logging.ERROR):
        _, _, songs = ids(await search(library, "lanterns", Broken()))
    assert songs == [LIGHTHOUSE, LOW_TIDE, TIDEWATER]
    assert "external search failed" in caplog.text


async def test_slow_catalog_is_cut_after_the_timeout(library: Database) -> None:
    class Slow(FakeMusicCatalog):
        async def search_songs(self, query: str, limit: int) -> list[CatalogTrack]:
            await asyncio.sleep(5)
            return await super().search_songs(query, limit)

    settings = SearchSettings(search_external_timeout_s=0.05)
    _, albums, songs = ids(await search(library, "bloom", Slow(), settings))
    assert songs == []
    assert albums == ["ytalbum:MPREb_Hn2Vq8Lr5Tz"]


def test_library_search_by_words(library: Database) -> None:
    with library.read() as conn:
        repo = LibrarySearch(conn)
        assert [s.id for s in repo.songs(USER, ["lanterns", "tide"], 10)] == [LOW_TIDE, TIDEWATER]
        # Every word must match: the album name and the title here.
        assert [s.id for s in repo.songs(USER, ["dusk", "tide"], 10)] == [LOW_TIDE]
        assert [s.id for s in repo.songs(USER, ["harbour"], 10)] == [LIGHTHOUSE, TIDEWATER]
        assert repo.songs(USER, ["glass"], 10) == []  # pending
        assert [a.id for a in repo.albums(USER, ["lights"], 10)] == [HARBOUR_LIGHTS]
        assert repo.albums(USER, ["bloom"], 10) == []
        assert repo.artists(USER, ["harbor"], 10) == []
        assert repo.songs_by_id(USER, []) == []
        assert repo.albums_by_id(USER, []) == []
        assert repo.artists_by_id(USER, []) == []
        (album,) = repo.albums_by_id(USER, [HARBOUR_LIGHTS])
        assert (album.song_count, album.duration_ms) == (2, 428_800)
        (artist,) = repo.artists_by_id(USER, [LANTERNS])
        assert artist.album_count == 2
        assert artist.starred_at is not None
        # LIKE wildcards in a query are literal.
        assert repo.songs(USER, ["%"], 10) == []
        assert repo.songs(USER, ["_"], 10) == []


def test_settings_are_read_once() -> None:
    assert search_settings() is search_settings()


async def test_duplicate_catalog_results_show_once(library: Database) -> None:
    class Twice(FakeMusicCatalog):
        async def search_songs(self, query: str, limit: int) -> list[CatalogTrack]:
            found = await super().search_songs(query, limit)
            return found + found

    _, _, songs = ids(await search(library, "bloom", Twice()))
    assert songs == ["yt:Hm3Vx8Nq2Lp", "yt:Tz9Kd4Wb7Rc[pending]", "yt:Pa6Ye1Uo3Gs"]


async def test_each_user_has_a_bucket_of_external_searches(
    library: Database, caplog: pytest.LogCaptureFixture
) -> None:
    """T22: past the per-user limit, search answers from the library only (no error), and the
    other users keep their own budget."""
    clock = FakeClock()
    limiter = SqliteRateLimiter(library, clock)
    settings = SearchSettings(search_user_rate_per_s=0.1, search_user_burst=2)
    service = SearchService(library, FakeMusicCatalog(), settings, limiter)

    async def songs(user: str | None) -> list[str]:
        found = await service.search(user, "lanterns", artists=ALL, albums=ALL, songs=ALL)
        return ids(found)[2]

    with_external = await songs(USER)
    assert any(s.startswith("yt:") for s in with_external)
    assert await songs(USER) == with_external
    with caplog.at_level(logging.INFO):
        assert await songs(USER) == [LIGHTHOUSE, LOW_TIDE, TIDEWATER]
    assert "external search limit" in caplog.text
    assert await songs("another-user") == with_external
    assert await songs(None) == with_external  # no user, no bucket (internal callers)
    clock.advance(10)
    assert await songs(USER) == with_external
    # The empty query never reaches YouTube Music and costs nothing.
    clock.advance(10)
    await service.search(USER, "", artists=ALL, albums=ALL, songs=ALL)
    assert limiter.hit(f"search:user:{USER}", Limit(0.1, 2)).allowed


def test_the_service_of_the_app_uses_the_shared_rate_limiter(library: Database) -> None:
    services = SimpleNamespace(db=library, catalog=FakeMusicCatalog(), rate_limiter=object())
    service = SearchService.of(services)  # type: ignore[arg-type]
    assert service._limiter is services.rate_limiter
