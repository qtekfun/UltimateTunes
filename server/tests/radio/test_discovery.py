# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Charts and moods: YouTube Music's public lists, mapped local-first (no new host)."""

from dataclasses import replace

import pytest

from tests.search.conftest import LIGHTHOUSE, LOW_TIDE, USER
from ultimatetunes.core.limits import DownloadLimits
from ultimatetunes.db import Database
from ultimatetunes.errors import FeatureDisabled
from ultimatetunes.radio.discovery import ChartsService
from ultimatetunes.radio.settings import RadioSettings
from ultimatetunes.search.fake import MOODS, FakeMusicCatalog
from ultimatetunes.search.library import LibrarySong
from ultimatetunes.search.service import ExternalSong, Song

pytestmark = pytest.mark.anyio


def key(song: Song) -> str:
    if isinstance(song, ExternalSong):
        return f"yt:{song.track.video_id}" + (f" ({song.state})" if song.state else "")
    return song.id


@pytest.fixture
def catalog() -> FakeMusicCatalog:
    return FakeMusicCatalog()


@pytest.fixture
def service(library: Database, catalog: FakeMusicCatalog) -> ChartsService:
    return ChartsService(library, catalog, RadioSettings())


async def test_charts_default_country_and_local_first(service: ChartsService) -> None:
    charts = await service.charts(USER, None, 50)
    assert charts.country == "ZZ"  # the default UT_CHARTS_COUNTRY
    keys = [key(s) for s in charts.items]
    # A video archived in the library becomes the library song; a pending one keeps its yt: id.
    assert LOW_TIDE in keys
    assert LIGHTHOUSE in keys
    assert "yt:Rb8Tn3ZcYv0 (pending)" in keys
    assert any(isinstance(s, LibrarySong) for s in charts.items)


async def test_charts_country_override_and_limit(service: ChartsService) -> None:
    charts = await service.charts(USER, "ES", 2)
    assert charts.country == "ES"
    assert len(charts.items) == 2


async def test_moods_and_mood_tracks(service: ChartsService) -> None:
    moods = await service.moods()
    assert [m.title for m in moods] == ["Chill", "Focus"]
    songs = await service.mood_tracks(USER, moods[0].params, 50)
    assert [key(s) for s in songs] == [LOW_TIDE, "yt:Rb8Tn3ZcYv0 (pending)"]


async def test_mood_tracks_unknown_category_is_empty(service: ChartsService) -> None:
    assert await service.mood_tracks(USER, "ggUnknown0000000000000", 50) == []


async def test_too_long_non_archived_songs_are_dropped(
    library: Database, catalog: FakeMusicCatalog
) -> None:
    # A too-long external song is dropped; a too-long but archived one stays (same rule as radio).
    catalog.tracks["Hm3Vx8Nq2Lp"] = replace(catalog.tracks["Hm3Vx8Nq2Lp"], duration_s=1801)
    catalog.tracks["Fk2Lp9QwXa1"] = replace(catalog.tracks["Fk2Lp9QwXa1"], duration_s=1801)
    service = ChartsService(library, catalog, RadioSettings())
    keys = [key(s) for s in (await service.charts(USER, "ZZ", 50)).items]
    assert "yt:Hm3Vx8Nq2Lp" not in keys
    assert LOW_TIDE in keys  # archived, kept despite the duration
    limits = DownloadLimits(max_track_duration_s=3600)
    roomy = ChartsService(library, catalog, RadioSettings(), limits)
    assert "yt:Hm3Vx8Nq2Lp" in [key(s) for s in (await roomy.charts(USER, "ZZ", 50)).items]


@pytest.mark.parametrize("settings", [RadioSettings(charts=False), RadioSettings(radio=False)])
async def test_charts_switched_off(
    library: Database, catalog: FakeMusicCatalog, settings: RadioSettings
) -> None:
    service = ChartsService(library, catalog, settings)
    with pytest.raises(FeatureDisabled):
        await service.charts(USER, None, 50)
    with pytest.raises(FeatureDisabled):
        await service.moods()
    with pytest.raises(FeatureDisabled):
        await service.mood_tracks(USER, MOODS[0].params, 50)
    assert catalog.calls == []
