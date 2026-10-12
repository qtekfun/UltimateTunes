# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Radio seeds and the local-first mapping, on the search test library and the fake catalog.

The fake radio of a video is that video, then every other fake song in catalog order:
Low Tide Letters (`Fk2…`, library), Glass Orchard (`Rb8…`, pending), Night Ferry (`Wq5…`, an
alias of the library song Lighthouse Keeper), Paper Moons (`Qx7…`, external), Static Bloom
(`Hm3…`, external), Signal Fires (`Tz9…`, pending), Harbor Lights (`Pa6…`, external).
"""

from dataclasses import replace

import pytest

from tests.search.conftest import (
    HARBOR,
    LANTERNS,
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
from ultimatetunes.errors import FeatureDisabled, InvalidId, NotFound, UpstreamUnavailable
from ultimatetunes.radio.service import Radio, RadioService, radio_settings
from ultimatetunes.radio.settings import RadioSettings
from ultimatetunes.search.catalog import CatalogArtistRef, CatalogTrack
from ultimatetunes.search.fake import FakeMusicCatalog
from ultimatetunes.search.library import LibrarySong
from ultimatetunes.search.service import ExternalSong, Song

pytestmark = pytest.mark.anyio

MERGED = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c009"
LONER = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01a009"
LONER_SONG = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c010"
UNKNOWN = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01ffff"


def key(song: Song) -> str:
    """The id a client sees, with the state of a not-archived song."""
    if isinstance(song, ExternalSong):
        return f"yt:{song.track.video_id}" + (f" ({song.state})" if song.state else "")
    return song.id


def keys(radio: Radio) -> list[str]:
    return [key(s) for s in radio.items]


@pytest.fixture
def catalog() -> FakeMusicCatalog:
    return FakeMusicCatalog()


@pytest.fixture
def service(library: Database, catalog: FakeMusicCatalog) -> RadioService:
    return RadioService(library, catalog, RadioSettings())


async def test_external_seed_maps_the_radio_local_first(service: RadioService) -> None:
    radio = await service.radio(USER, "yt:Qx7Lm2pZ0aB", 50)
    assert key(radio.seed) == "yt:Qx7Lm2pZ0aB"
    assert not radio.from_artist
    assert keys(radio) == [
        LOW_TIDE,
        "yt:Rb8Tn3ZcYv0 (pending)",
        LIGHTHOUSE,
        "yt:Hm3Vx8Nq2Lp",
        "yt:Tz9Kd4Wb7Rc (pending)",
        "yt:Pa6Ye1Uo3Gs",
    ]
    lighthouse = radio.items[2]
    # Library songs carry the caller's own fields.
    assert isinstance(lighthouse, LibrarySong)
    assert lighthouse.starred_at == NOW
    assert lighthouse.play_count == 14


async def test_per_user_fields_are_empty_without_a_user(service: RadioService) -> None:
    radio = await service.radio(None, "yt:Qx7Lm2pZ0aB", 50)
    lighthouse = radio.items[2]
    assert isinstance(lighthouse, LibrarySong)
    assert lighthouse.starred_at is None


async def test_limit_counts_items_after_the_seed(service: RadioService) -> None:
    radio = await service.radio(USER, "yt:Qx7Lm2pZ0aB", 2)
    assert keys(radio) == [LOW_TIDE, "yt:Rb8Tn3ZcYv0 (pending)"]


async def test_yt_seed_of_an_archived_video_is_the_library_song(service: RadioService) -> None:
    radio = await service.radio(USER, "yt:Wq5Jd7HsKe2", 50)
    assert key(radio.seed) == LIGHTHOUSE
    assert LIGHTHOUSE not in keys(radio)
    assert keys(radio)[:2] == [LOW_TIDE, "yt:Rb8Tn3ZcYv0 (pending)"]


async def test_library_seed_uses_its_alias(
    service: RadioService, catalog: FakeMusicCatalog
) -> None:
    # Lighthouse Keeper has no yt_video_id, only the alias yt:Wq5Jd7HsKe2.
    radio = await service.radio(USER, LIGHTHOUSE.upper(), 50)
    assert key(radio.seed) == LIGHTHOUSE
    assert "yt:Wq5Jd7HsKe2" not in keys(radio)
    assert LIGHTHOUSE not in keys(radio)
    assert catalog.calls == ["radio"]


async def test_library_seed_uses_its_video(service: RadioService) -> None:
    radio = await service.radio(USER, LOW_TIDE, 50)
    assert key(radio.seed) == LOW_TIDE
    assert keys(radio)[0] == "yt:Rb8Tn3ZcYv0 (pending)"
    assert LOW_TIDE not in keys(radio)


async def test_pending_library_seed_shows_as_pending(service: RadioService) -> None:
    radio = await service.radio(USER, ORCHARD, 50)
    assert key(radio.seed) == "yt:Rb8Tn3ZcYv0 (pending)"
    assert "yt:Rb8Tn3ZcYv0 (pending)" not in keys(radio)


async def test_merged_library_seed_follows_its_track(library: Database) -> None:
    with library.transaction() as conn:
        conn.execute(
            "INSERT INTO tracks (id, status, title, title_norm, artist_name, merged_into,"
            " created_at, updated_at) VALUES (?, 'merged', 'Old', 'old', 'X', ?, ?, ?)",
            (MERGED, LOW_TIDE, NOW, NOW),
        )
    radio = await RadioService(library, FakeMusicCatalog(), RadioSettings()).radio(USER, MERGED, 50)
    assert key(radio.seed) == LOW_TIDE


async def test_library_seed_without_video_searches_the_catalog(
    service: RadioService, catalog: FakeMusicCatalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[tuple[str, int]] = []

    async def search_songs(query: str, limit: int) -> list[CatalogTrack]:
        asked.append((query, limit))
        return [catalog.tracks["Hm3Vx8Nq2Lp"]]

    monkeypatch.setattr(catalog, "search_songs", search_songs)
    radio = await service.radio(USER, TIDEWATER, 50)
    assert asked == [("Tidewater The Paper Lanterns", 1)]
    # The seed stays the library song; the radio is the one of the match.
    assert key(radio.seed) == TIDEWATER
    assert "yt:Hm3Vx8Nq2Lp" not in keys(radio)
    assert keys(radio)[0] == LOW_TIDE


async def test_library_seed_without_any_match_is_not_found(service: RadioService) -> None:
    with pytest.raises(NotFound):
        await service.radio(USER, TIDEWATER, 50)


async def test_seed_missing_from_its_radio_is_fetched(
    service: RadioService, catalog: FakeMusicCatalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def radio(video_id: str, limit: int) -> list[CatalogTrack]:
        return [catalog.tracks["Pa6Ye1Uo3Gs"], catalog.tracks["Fk2Lp9QwXa1"]]

    monkeypatch.setattr(catalog, "radio", radio)
    result = await service.radio(USER, "yt:Qx7Lm2pZ0aB", 50)
    assert key(result.seed) == "yt:Qx7Lm2pZ0aB"
    assert keys(result) == ["yt:Pa6Ye1Uo3Gs", LOW_TIDE]
    assert catalog.calls == ["track"]
    # Without the seed in it, the radio can be one song longer than the limit.
    shorter = await service.radio(USER, "yt:Qx7Lm2pZ0aB", 1)
    assert keys(shorter) == ["yt:Pa6Ye1Uo3Gs"]


async def test_a_song_appears_once(library: Database, catalog: FakeMusicCatalog) -> None:
    with library.transaction() as conn:
        conn.execute(
            "INSERT INTO track_aliases (alias, track_id, created_at) VALUES (?, ?, ?)",
            ("yt:Hm3Vx8Nq2Lp", LIGHTHOUSE, NOW),
        )
        conn.execute(
            "INSERT INTO track_aliases (alias, track_id, created_at) VALUES (?, ?, ?)",
            ("yt:Pa6Ye1Uo3Gs", SIGNAL, NOW),
        )
    radio = await RadioService(library, catalog, RadioSettings()).radio(USER, "yt:Qx7Lm2pZ0aB", 50)
    assert keys(radio) == [
        LOW_TIDE,
        "yt:Rb8Tn3ZcYv0 (pending)",
        LIGHTHOUSE,
        "yt:Tz9Kd4Wb7Rc (pending)",
    ]


async def test_a_song_seed_is_never_repeated(library: Database, catalog: FakeMusicCatalog) -> None:
    # Another video of the seed's own track comes later in the radio.
    with library.transaction() as conn:
        conn.execute(
            "INSERT INTO track_aliases (alias, track_id, created_at) VALUES (?, ?, ?)",
            ("yt:Pa6Ye1Uo3Gs", LOW_TIDE, NOW),
        )
    radio = await RadioService(library, catalog, RadioSettings()).radio(USER, LOW_TIDE, 50)
    assert LOW_TIDE not in keys(radio)
    assert "yt:Pa6Ye1Uo3Gs" not in keys(radio)


@pytest.mark.parametrize(
    "seed",
    [
        "ytalbum:MPREb_k3Vd9QmT2xL",
        "ytartist:UCq8XbV1r0LwZ5mN3tYp7kQe",
        "yt:short",
        "yt:Qx7Lm2pZ0aB ",
        "nonsense",
        "",
    ],
)
async def test_song_radio_rejects_other_ids(service: RadioService, seed: str) -> None:
    with pytest.raises(InvalidId):
        await service.radio(USER, seed, 50)


async def test_unknown_seeds_are_not_found(service: RadioService) -> None:
    with pytest.raises(NotFound):
        await service.radio(USER, UNKNOWN, 50)
    with pytest.raises(NotFound):
        await service.radio(USER, "yt:Zz0Zz0Zz0Zz", 50)
    with pytest.raises(NotFound):
        await service.radio(USER, UNKNOWN, 50, artists=True)


async def test_album_ids_are_invalid_even_with_artists(service: RadioService) -> None:
    with pytest.raises(InvalidId):
        await service.radio(USER, "ytalbum:MPREb_k3Vd9QmT2xL", 50, artists=True)


# ---------------------------------------------------------------------- artist seeds


async def test_external_artist_seed_starts_from_its_top_song(service: RadioService) -> None:
    radio = await service.radio(USER, "ytartist:UCn4HbR7oQ2sLx9TzV0eWm3K", 50, artists=True)
    assert radio.from_artist
    assert key(radio.seed) == "yt:Hm3Vx8Nq2Lp"
    assert keys(radio)[0] == LOW_TIDE


async def test_library_artist_seed_uses_its_channel(
    service: RadioService, catalog: FakeMusicCatalog
) -> None:
    radio = await service.radio(USER, LANTERNS, 50, artists=True)
    assert radio.from_artist
    # The top song of The Paper Lanterns is archived: the seed is the library song.
    assert key(radio.seed) == LOW_TIDE
    assert catalog.calls == ["artist", "radio"]


async def test_library_artist_without_channel_uses_its_first_song(library: Database) -> None:
    with library.transaction() as conn:
        conn.execute(
            "INSERT INTO artists (id, name, name_norm, created_at, updated_at)"
            " VALUES (?, 'Loner', 'loner', ?, ?)",
            (LONER, NOW, NOW),
        )
        conn.execute(
            "INSERT INTO tracks (id, status, title, title_norm, artist_id, artist_name,"
            " yt_video_id, created_at, updated_at)"
            " VALUES (?, 'ready', 'Solo', 'solo', ?, 'Loner', 'Pa6Ye1Uo3Gs', ?, ?)",
            (LONER_SONG, LONER, NOW, NOW),
        )
    radio = await RadioService(library, FakeMusicCatalog(), RadioSettings()).radio(
        USER, LONER, 50, artists=True
    )
    assert radio.from_artist
    assert key(radio.seed) == LONER_SONG
    assert "yt:Pa6Ye1Uo3Gs" not in keys(radio)


async def test_library_artist_without_songs_is_not_found(library: Database) -> None:
    with library.transaction() as conn:
        conn.execute(
            "INSERT INTO artists (id, name, name_norm, created_at, updated_at)"
            " VALUES (?, 'Loner', 'loner', ?, ?)",
            (LONER, NOW, NOW),
        )
    service = RadioService(library, FakeMusicCatalog(), RadioSettings())
    with pytest.raises(NotFound):
        await service.radio(USER, LONER, 50, artists=True)


async def test_artist_without_top_songs_is_not_found(
    service: RadioService, catalog: FakeMusicCatalog
) -> None:
    catalog.artists["UCempty0000000000000000x"] = CatalogArtistRef(
        "UCempty0000000000000000x", "Nobody"
    )
    with pytest.raises(NotFound):
        await service.radio(USER, "ytartist:UCempty0000000000000000x", 50, artists=True)


async def test_artist_ids_need_artists(service: RadioService) -> None:
    # A library artist UUID is not a song.
    with pytest.raises(NotFound):
        await service.radio(USER, HARBOR, 50)


# ---------------------------------------------------------------------- errors and settings


async def test_catalog_failures_surface(service: RadioService, catalog: FakeMusicCatalog) -> None:
    catalog.fail_with = UpstreamUnavailable()
    with pytest.raises(UpstreamUnavailable):
        await service.radio(USER, "yt:Qx7Lm2pZ0aB", 50)


async def test_switched_off(library: Database, catalog: FakeMusicCatalog) -> None:
    service = RadioService(library, catalog, RadioSettings(radio=False))
    with pytest.raises(FeatureDisabled):
        await service.radio(USER, "yt:Qx7Lm2pZ0aB", 50)
    assert catalog.calls == []


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UT_RADIO", "false")
    assert not RadioSettings().radio
    radio_settings.cache_clear()
    try:
        assert not radio_settings().radio
    finally:
        radio_settings.cache_clear()


async def test_a_radio_keeps_nothing(service: RadioService, library: Database) -> None:
    """Listing a radio is not a "keep" action: no pending track, alias or job (ids.md)."""

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
    await service.radio(USER, "yt:Qx7Lm2pZ0aB", 50)
    await service.radio(USER, "ytartist:UCn4HbR7oQ2sLx9TzV0eWm3K", 50, artists=True)
    await service.radio(USER, ORCHARD, 50)
    assert counts() == before


async def test_songs_too_long_to_download_are_left_out_unless_archived(
    library: Database, catalog: FakeMusicCatalog
) -> None:
    for video in ("Rb8Tn3ZcYv0", "Hm3Vx8Nq2Lp", "Fk2Lp9QwXa1"):
        catalog.tracks[video] = replace(catalog.tracks[video], duration_s=1801)
    radio = await RadioService(library, catalog, RadioSettings()).radio(USER, "yt:Qx7Lm2pZ0aB", 50)
    shown = keys(radio)
    # Pending and unknown ones are dropped; the archived one (LOW_TIDE) stays.
    assert "yt:Rb8Tn3ZcYv0 (pending)" not in shown
    assert "yt:Hm3Vx8Nq2Lp" not in shown
    assert LOW_TIDE in shown
    roomy = DownloadLimits(max_track_duration_s=3600)
    everything = await RadioService(library, catalog, RadioSettings(), roomy).radio(
        USER, "yt:Qx7Lm2pZ0aB", 50
    )
    assert "yt:Hm3Vx8Nq2Lp" in keys(everything)
