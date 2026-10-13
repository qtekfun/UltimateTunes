# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Recommendations from the caller's plays and favourites, seeded into the fake radio.

The fake radio of a video is that video, then every other fake song in catalog order (see
`tests/radio/test_routes`). The search test library gives ana one seed already: Lighthouse
Keeper (played 14 times, starred), whose only video is the alias `yt:Wq5Jd7HsKe2`.
"""

from dataclasses import replace

import pytest

from tests.search.conftest import (
    LIGHTHOUSE,
    LOW_TIDE,
    NOW,
    ORCHARD,
    SIGNAL,
    TIDEWATER,
    USER,
)
from ultimatetunes.core.limits import DownloadLimits
from ultimatetunes.db import Database
from ultimatetunes.db.driver import Connection
from ultimatetunes.errors import FeatureDisabled
from ultimatetunes.radio.external import SourceShelf
from ultimatetunes.radio.recommendations import RecommendationsService
from ultimatetunes.radio.settings import RadioSettings
from ultimatetunes.search.fake import FakeMusicCatalog
from ultimatetunes.search.library import LibrarySong
from ultimatetunes.search.service import ExternalSong, Song

pytestmark = pytest.mark.anyio

OTHER = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01e002"


def key(song: Song) -> str:
    """The id a client sees, with the state of a not-archived song."""
    if isinstance(song, ExternalSong):
        return f"yt:{song.track.video_id}" + (f" ({song.state})" if song.state else "")
    return song.id


def keys(songs: object) -> list[str]:
    assert isinstance(songs, (list, tuple))
    return [key(s) for s in songs]


@pytest.fixture
def catalog() -> FakeMusicCatalog:
    return FakeMusicCatalog()


@pytest.fixture
def service(library: Database, catalog: FakeMusicCatalog) -> RecommendationsService:
    return RecommendationsService(library, catalog, RadioSettings())


def _play_count(conn: Connection, user: str, track: str, count: int) -> None:
    conn.execute(
        "INSERT INTO user_track_stats (user_id, track_id, play_count, last_played_at)"
        " VALUES (?, ?, ?, ?)",
        (user, track, count, NOW),
    )


def _other_user(conn: Connection) -> None:
    conn.execute(
        "INSERT INTO users (id, username, password_hash, role, created_at, updated_at)"
        " VALUES (?, 'ben', 'x', 'user', ?, ?)",
        (OTHER, NOW, NOW),
    )


async def test_single_seed_from_plays_and_favourites(service: RecommendationsService) -> None:
    recs = await service.recommend(USER, 20)
    # One seed: Lighthouse Keeper, reached through its alias yt:Wq5Jd7HsKe2.
    assert len(recs.because_you_played) == 1
    shelf = recs.because_you_played[0]
    assert key(shelf.seed) == LIGHTHOUSE
    # The seed's own video is left out; the rest of its radio becomes the shelf, local-first.
    expected = [
        LOW_TIDE,
        "yt:Rb8Tn3ZcYv0 (pending)",
        "yt:Qx7Lm2pZ0aB",
        "yt:Hm3Vx8Nq2Lp",
        "yt:Tz9Kd4Wb7Rc (pending)",
        "yt:Pa6Ye1Uo3Gs",
    ]
    assert keys(shelf.items) == expected
    # With one seed, the aggregated shelf is the same set in the same order.
    assert keys(recs.recommended_for_you) == expected
    # A library song in the shelf carries the caller's own fields.
    low_tide = shelf.items[0]
    assert isinstance(low_tide, LibrarySong)


async def test_songs_the_caller_already_plays_are_not_recommended(
    library: Database, service: RecommendationsService
) -> None:
    # ana already plays Low Tide Letters: it must not come back as a recommendation.
    with library.transaction() as conn:
        _play_count(conn, USER, LOW_TIDE, 5)
    recs = await service.recommend(USER, 20)
    all_keys = keys(recs.recommended_for_you)
    assert LOW_TIDE not in all_keys
    for shelf in recs.because_you_played:
        assert LOW_TIDE not in keys(shelf.items)


async def test_two_seeds_rank_by_agreement(
    library: Database, service: RecommendationsService
) -> None:
    with library.transaction() as conn:
        _play_count(conn, USER, LOW_TIDE, 10)
    recs = await service.recommend(USER, 20)
    # Seeds, most played first: Lighthouse Keeper (14) then Low Tide Letters (10).
    assert keys([s.seed for s in recs.because_you_played]) == [LIGHTHOUSE, LOW_TIDE]
    # Both radios agree on these five new songs (each seed's own video is excluded).
    agreed = [
        "yt:Rb8Tn3ZcYv0 (pending)",
        "yt:Qx7Lm2pZ0aB",
        "yt:Hm3Vx8Nq2Lp",
        "yt:Tz9Kd4Wb7Rc (pending)",
        "yt:Pa6Ye1Uo3Gs",
    ]
    assert keys(recs.recommended_for_you) == agreed


async def test_seed_count_setting_is_respected(
    library: Database, catalog: FakeMusicCatalog
) -> None:
    with library.transaction() as conn:
        _play_count(conn, USER, LOW_TIDE, 10)
    service = RecommendationsService(library, catalog, RadioSettings(recommendation_seeds=1))
    recs = await service.recommend(USER, 20)
    assert len(recs.because_you_played) == 1
    assert key(recs.because_you_played[0].seed) == LIGHTHOUSE


async def test_a_favourite_never_played_still_seeds(
    library: Database, service: RecommendationsService
) -> None:
    # ben only stars Low Tide Letters (ready, video yt:Fk2Lp9QwXa1); he never played it.
    with library.transaction() as conn:
        _other_user(conn)
        conn.execute(
            "INSERT INTO starred_tracks (user_id, track_id, starred_at) VALUES (?, ?, ?)",
            (OTHER, LOW_TIDE, NOW),
        )
    recs = await service.recommend(OTHER, 20)
    assert [key(s.seed) for s in recs.because_you_played] == [LOW_TIDE]
    shelf = recs.because_you_played[0]
    # The seed is dropped; a library song ben has not played (Lighthouse Keeper) is offered.
    assert LOW_TIDE not in keys(shelf.items)
    assert LIGHTHOUSE in keys(shelf.items)


async def test_limit_truncates_every_shelf(
    library: Database, service: RecommendationsService
) -> None:
    with library.transaction() as conn:
        _play_count(conn, USER, LOW_TIDE, 10)
    recs = await service.recommend(USER, 2)
    assert len(recs.recommended_for_you) == 2
    for shelf in recs.because_you_played:
        assert len(shelf.items) == 2


async def test_no_plays_or_favourites_is_empty_and_calls_nothing(
    library: Database, catalog: FakeMusicCatalog, service: RecommendationsService
) -> None:
    with library.transaction() as conn:
        _other_user(conn)
    recs = await service.recommend(OTHER, 20)
    assert recs.recommended_for_you == []
    assert recs.because_you_played == []
    assert catalog.calls == []


async def test_recommendations_switched_off(library: Database, catalog: FakeMusicCatalog) -> None:
    service = RecommendationsService(library, catalog, RadioSettings(recommendations=False))
    with pytest.raises(FeatureDisabled):
        await service.recommend(USER, 20)
    assert catalog.calls == []


async def test_radio_switched_off_also_disables_recommendations(
    library: Database, catalog: FakeMusicCatalog
) -> None:
    service = RecommendationsService(library, catalog, RadioSettings(radio=False))
    with pytest.raises(FeatureDisabled):
        await service.recommend(USER, 20)
    assert catalog.calls == []


async def test_recommendations_keep_nothing(
    service: RecommendationsService, library: Database
) -> None:
    """Listing recommendations is not a "keep": no new track, alias or job (ids.md)."""

    def counts() -> list[object]:
        with library.read() as conn:
            return [
                conn.execute(sql).fetchall()
                for sql in (
                    "SELECT COUNT(*) AS n FROM tracks",
                    "SELECT COUNT(*) AS n FROM track_aliases",
                    "SELECT COUNT(*) AS n FROM jobs",
                )
            ]

    before = counts()
    await service.recommend(USER, 20)
    assert counts() == before


async def test_too_long_external_songs_are_left_out_unless_archived(
    library: Database, catalog: FakeMusicCatalog
) -> None:
    for video in ("Rb8Tn3ZcYv0", "Hm3Vx8Nq2Lp", "Fk2Lp9QwXa1"):
        catalog.tracks[video] = replace(catalog.tracks[video], duration_s=1801)
    service = RecommendationsService(library, catalog, RadioSettings())
    recs = await service.recommend(USER, 20)
    shown = keys(recs.recommended_for_you)
    # Pending/unknown over the limit are dropped; the archived Low Tide Letters stays.
    assert "yt:Rb8Tn3ZcYv0 (pending)" not in shown
    assert "yt:Hm3Vx8Nq2Lp" not in shown
    assert LOW_TIDE in shown
    roomy = DownloadLimits(max_track_duration_s=3600)
    everything = await RecommendationsService(library, catalog, RadioSettings(), roomy).recommend(
        USER, 20
    )
    assert "yt:Hm3Vx8Nq2Lp" in keys(everything.recommended_for_you)


async def test_a_seed_without_a_video_is_skipped(
    library: Database, catalog: FakeMusicCatalog, service: RecommendationsService
) -> None:
    # ben only plays Tidewater, which has neither a yt_video_id nor an alias: nothing to seed.
    with library.transaction() as conn:
        _other_user(conn)
        _play_count(conn, OTHER, TIDEWATER, 7)
    recs = await service.recommend(OTHER, 20)
    assert recs.because_you_played == []
    assert recs.recommended_for_you == []
    assert catalog.calls == []


async def test_a_song_appears_once_in_a_shelf(
    library: Database, catalog: FakeMusicCatalog, service: RecommendationsService
) -> None:
    # Harbor Lights (yt:Pa6Ye1Uo3Gs) is made another alias of Low Tide Letters, so the seed's
    # radio lists that library song twice; it must appear once.
    with library.transaction() as conn:
        conn.execute(
            "INSERT INTO track_aliases (alias, track_id, created_at) VALUES (?, ?, ?)",
            ("yt:Pa6Ye1Uo3Gs", LOW_TIDE, NOW),
        )
    recs = await service.recommend(USER, 20)
    shelf = recs.because_you_played[0]
    assert keys(shelf.items).count(LOW_TIDE) == 1
    assert "yt:Pa6Ye1Uo3Gs" not in keys(shelf.items)


async def test_a_radio_with_no_new_songs_makes_no_shelf(
    service: RecommendationsService, catalog: FakeMusicCatalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def radio(video_id: str, limit: int) -> list[object]:
        return [catalog.tracks[video_id]]

    monkeypatch.setattr(catalog, "radio", radio)
    recs = await service.recommend(USER, 20)
    assert recs.because_you_played == []
    assert recs.recommended_for_you == []


class _StubSource:
    """Records what the recommender passes and returns one shelf."""

    source = "stub"

    def __init__(self) -> None:
        self.seen: list[tuple[str, int, frozenset[str]]] = []

    async def shelves(self, user_id: str, limit: int, blocked: frozenset[str]) -> list[SourceShelf]:
        self.seen.append((user_id, limit, blocked))
        return [SourceShelf("stub", "Stub shelf", [])]


async def test_external_shelves_are_appended_with_the_caller_rotation_blocked(
    library: Database, catalog: FakeMusicCatalog
) -> None:
    source = _StubSource()
    service = RecommendationsService(library, catalog, RadioSettings(), sources=[source])
    recs = await service.recommend(USER, 20)
    assert [s.source for s in recs.shelves] == ["stub"]
    # The caller's seeds (Lighthouse Keeper) and played songs are blocked for the source too.
    user_id, limit, blocked = source.seen[0]
    assert (user_id, limit) == (USER, 20)
    assert LIGHTHOUSE in blocked


async def test_external_shelves_run_even_without_song_seeds(
    library: Database, catalog: FakeMusicCatalog
) -> None:
    source = _StubSource()
    service = RecommendationsService(library, catalog, RadioSettings(), sources=[source])
    with library.transaction() as conn:
        _other_user(conn)
    recs = await service.recommend(OTHER, 20)
    assert recs.recommended_for_you == []
    assert recs.because_you_played == []
    assert [s.source for s in recs.shelves] == ["stub"]
    assert source.seen[0][2] == frozenset()
    # No song seed means no YouTube Music radio call; only the external source ran.
    assert catalog.calls == []


async def test_pending_seed_is_resolved_and_used(
    library: Database, service: RecommendationsService
) -> None:
    # A pending favourite (Glass Orchard, video yt:Rb8Tn3ZcYv0) still seeds a radio.
    with library.transaction() as conn:
        _other_user(conn)
        conn.execute(
            "INSERT INTO starred_tracks (user_id, track_id, starred_at) VALUES (?, ?, ?)",
            (OTHER, ORCHARD, NOW),
        )
    recs = await service.recommend(OTHER, 20)
    assert [key(s.seed) for s in recs.because_you_played] == ["yt:Rb8Tn3ZcYv0 (pending)"]
    # Signal Fires (also pending) is a new song from that radio, kept as its yt: id.
    items = recs.because_you_played[0].items
    assert "yt:Tz9Kd4Wb7Rc (pending)" in keys(items)
    assert SIGNAL not in [s.id for s in items if isinstance(s, LibrarySong)]
