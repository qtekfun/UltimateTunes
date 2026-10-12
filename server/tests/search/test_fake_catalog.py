# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""FakeMusicCatalog: invented data in the id formats of contracts/ids.md."""

import re

import pytest

from ultimatetunes.errors import FeatureNotImplemented, NotFound, UpstreamUnavailable
from ultimatetunes.search.catalog import (
    CatalogThrottled,
    UnavailableCatalog,
    build_catalog,
)
from ultimatetunes.search.fake import PLAYLIST_ID, FakeMusicCatalog
from ultimatetunes.settings import Settings

pytestmark = pytest.mark.anyio
VIDEO = re.compile(r"^[A-Za-z0-9_-]{11}$")
OTHER = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_ids_follow_the_contract() -> None:
    catalog = FakeMusicCatalog()
    assert all(VIDEO.match(v) for v in catalog.tracks)
    assert all(OTHER.match(b) for b in catalog.albums)
    assert all(OTHER.match(c) for c in catalog.artists)


async def test_search_album_artist_track_radio_playlist() -> None:
    catalog = FakeMusicCatalog()
    songs = await catalog.search_songs("lanterns", 2)
    assert len(songs) == 2
    assert await catalog.search_songs("  ", 10) == []
    assert [a.title for a in await catalog.search_albums("static", 5)] == ["Static Bloom"]
    assert [a.name for a in await catalog.search_artists("neon", 5)] == ["Neon Harbor"]
    album = await catalog.album("MPREb_k3Vd9QmT2xL")
    assert [t.track_number for t in album.tracks] == [1, 2, 3, 4]
    artist = await catalog.artist("UCq8XbV1r0LwZ5mN3tYp7kQe")
    assert artist.albums[0].browse_id == "MPREb_k3Vd9QmT2xL"
    assert (await catalog.track("Qx7Lm2pZ0aB")).title == "Paper Moons (Live)"
    radio = await catalog.radio("Qx7Lm2pZ0aB", 3)
    assert radio[0].video_id == "Qx7Lm2pZ0aB"
    assert len(radio) == 3
    playlist = await catalog.playlist(PLAYLIST_ID)
    assert len(playlist.tracks) == 3
    assert "search_songs" in catalog.calls


async def test_unknown_ids_are_not_found() -> None:
    catalog = FakeMusicCatalog()
    for call in (
        catalog.album("MPREb_nope"),
        catalog.artist("UCnope"),
        catalog.track("AAAAAAAAAAA"),
        catalog.radio("AAAAAAAAAAA", 5),
        catalog.playlist("PLnope"),
    ):
        with pytest.raises(NotFound):
            await call


async def test_failures_can_be_injected() -> None:
    catalog = FakeMusicCatalog()
    catalog.fail_with = CatalogThrottled()
    with pytest.raises(UpstreamUnavailable):
        await catalog.search_songs("x", 1)


async def test_unavailable_catalog_until_t06(settings: Settings) -> None:
    catalog = build_catalog(settings)
    assert isinstance(catalog, UnavailableCatalog)
    for call in (
        catalog.search_songs("x", 1),
        catalog.search_albums("x", 1),
        catalog.search_artists("x", 1),
        catalog.album("x"),
        catalog.artist("x"),
        catalog.track("x"),
        catalog.radio("x", 1),
        catalog.playlist("x"),
    ):
        with pytest.raises(FeatureNotImplemented):
            await call
    fake = build_catalog(settings.model_copy(update={"fake_youtube": True}))
    assert isinstance(fake, FakeMusicCatalog)
