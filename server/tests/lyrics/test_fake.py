# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The test stack's LRCLIB (`UT_FAKE_YOUTUBE`): lyrics with no outbound request."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from tests.conftest import CONTRACTS
from tests.lyrics.helpers import TRACK_ID, add_track
from tests.lyrics.test_route import AllowAll
from ultimatetunes.app import create_app
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.services import Services, build_services
from ultimatetunes.db import migrate
from ultimatetunes.lyrics.fake import FakeLrclib
from ultimatetunes.lyrics.lrclib import LrclibClient, LrclibQuery
from ultimatetunes.lyrics.service import build_lyrics_service
from ultimatetunes.settings import Settings


def test_fake_records() -> None:
    fake = FakeLrclib()
    found = fake.get(LrclibQuery("Lighthouse Keeper", "The Paper Lanterns"))
    assert found is not None
    assert not found.instrumental
    assert found.synced_lyrics is not None
    assert found.synced_lyrics.startswith("[00:00.00] Lighthouse Keeper, first line")
    assert found.plain_lyrics is not None
    assert found == fake.get(LrclibQuery("Lighthouse Keeper", "The Paper Lanterns"))
    instrumental = fake.get(LrclibQuery("Tide (Instrumental)", "A"))
    assert instrumental is not None
    assert instrumental.instrumental
    assert instrumental.synced_lyrics is None
    assert fake.get(LrclibQuery("Song With No Lyrics", "A")) is None
    assert len(fake.queries) == 4


@pytest.fixture
def services(settings: Settings, clock: FakeClock) -> Iterator[Services]:
    conn = migrate.connect(settings.database_file)
    migrate.migrate(conn, CONTRACTS / "db" / "migrations", clock)
    conn.close()
    svc = build_services(settings, clock)  # conftest: fake_youtube=True
    svc.authenticator = AllowAll()
    yield svc
    svc.db.close()


def test_the_test_stack_uses_the_fake(services: Services) -> None:
    assert isinstance(build_lyrics_service(services).client, FakeLrclib)
    services.settings = services.settings.model_copy(update={"fake_youtube": False})
    assert isinstance(build_lyrics_service(services).client, LrclibClient)


def test_lyrics_by_song_id_without_network(services: Services, clock: FakeClock) -> None:
    add_track(services.db, clock)
    with TestClient(create_app(services=services)) as client:
        r = client.get("/rest/getLyricsBySongId", params={"id": TRACK_ID, "f": "json"})
    assert r.status_code == 200
    lyrics = r.json()["subsonic-response"]["lyricsList"]["structuredLyrics"]
    assert lyrics[0]["synced"] is True
    assert "first line" in lyrics[0]["line"][0]["value"]
