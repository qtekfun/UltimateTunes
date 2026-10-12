# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`getLyricsBySongId` through the OpenSubsonic pipeline, JSON and XML, against the contract."""

import json
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
import respx
import yaml  # type: ignore[import-untyped]  # dev-only, via schemathesis
from fastapi.testclient import TestClient

from tests.lyrics.helpers import TRACK_ID, VIDEO_ID, add_track, fixture_bytes
from ultimatetunes.app import create_app
from ultimatetunes.core.authn import Principal
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.services import Services, build_services
from ultimatetunes.db import migrate
from ultimatetunes.lyrics.service import build_lyrics_service
from ultimatetunes.lyrics.settings import LyricsSettings
from ultimatetunes.settings import Settings

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"


def examples() -> dict[str, Any]:
    spec = yaml.safe_load(
        (CONTRACTS / "openapi" / "opensubsonic-subset.yaml").read_text(encoding="utf-8")
    )
    found: dict[str, Any] = spec["components"]["examples"]
    return found


class AllowAll:
    principal = Principal("0199d6a2-4c1e-7b3a-9f10-2a6c8e01e001", "ana", "user")

    def authenticate_subsonic(
        self, params: Mapping[str, Sequence[str]], client_ip: str | None
    ) -> Principal:
        return self.principal

    def authenticate_api_key(
        self, header_key: str | None, query_key: str | None, client_ip: str | None
    ) -> Principal:
        return self.principal


@pytest.fixture
def services(settings: Settings, clock: FakeClock) -> Services:
    conn = migrate.connect(settings.database_file)
    migrate.migrate(conn, CONTRACTS / "db" / "migrations", clock)
    conn.close()
    svc = build_services(settings, clock)
    svc.authenticator = AllowAll()
    return svc


@pytest.fixture
def client(services: Services) -> Iterator[TestClient]:
    with TestClient(create_app(services=services)) as test_client:
        yield test_client


def synced_only(lrclib: respx.MockRouter) -> respx.Route:
    record = json.loads(fixture_bytes("lighthouse_keeper.json"))
    record["plainLyrics"] = None
    return lrclib.get("/api/get").respond(200, json=record)


def test_json_matches_the_contract_example(
    client: TestClient, services: Services, clock: FakeClock, lrclib: respx.MockRouter
) -> None:
    add_track(services.db, clock)
    synced_only(lrclib)
    r = client.get("/rest/getLyricsBySongId", params={"id": TRACK_ID, "f": "json"})
    assert r.status_code == 200
    body = r.json()["subsonic-response"]
    expected = examples()["getLyricsBySongId_ok"]["value"]["subsonic-response"]
    assert body["status"] == "ok"
    assert body["lyricsList"] == expected["lyricsList"]


def test_xml_matches_the_contract_example(
    client: TestClient, services: Services, clock: FakeClock, lrclib: respx.MockRouter
) -> None:
    add_track(services.db, clock)
    synced_only(lrclib)
    r = client.post(
        "/rest/getLyricsBySongId.view", data={"id": TRACK_ID, "enhanced": "true", "f": "xml"}
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/xml")
    expected: str = examples()["getLyricsBySongId_ok_xml"]["value"]
    block = expected[expected.index("  <lyricsList>") : expected.index("</lyricsList>")]
    assert block in r.text


def test_plain_and_synced_in_xml(
    client: TestClient, services: Services, clock: FakeClock, lrclib: respx.MockRouter
) -> None:
    add_track(services.db, clock, alias=f"yt:{VIDEO_ID}")
    lrclib.get("/api/get").respond(200, content=fixture_bytes("lighthouse_keeper.json"))
    r = client.get("/rest/getLyricsBySongId", params={"id": f"yt:{VIDEO_ID}"})
    assert r.text.index('synced="true"') < r.text.index('synced="false"')
    assert "<line>Salt on the window, the night coming in</line>" in r.text


@pytest.mark.parametrize("fmt", ["json", "xml"])
def test_no_lyrics_is_an_empty_list(client: TestClient, fmt: str) -> None:
    r = client.get("/rest/getLyricsBySongId", params={"id": "yt:AAAAAAAAAAA", "f": fmt})
    assert r.status_code == 200
    if fmt == "json":
        assert r.json()["subsonic-response"]["lyricsList"] == {"structuredLyrics": []}
    else:
        assert "<lyricsList/>" in r.text


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({}, 10),
        ({"id": ""}, 10),
        ({"id": "ytalbum:MPREb_k3Vd9QmT2xL"}, 70),
        ({"id": "0199d6a2-4c1e-7b3a-9f10-2a6c8e01ffff"}, 70),
    ],
)
def test_errors(client: TestClient, params: dict[str, str], code: int) -> None:
    r = client.get("/rest/getLyricsBySongId", params={**params, "f": "json"})
    assert r.status_code == 200
    assert r.json()["subsonic-response"]["error"]["code"] == code


def test_lrclib_down_is_error_zero(
    client: TestClient, services: Services, clock: FakeClock, lrclib: respx.MockRouter
) -> None:
    add_track(services.db, clock)
    lrclib.get("/api/get").respond(500)
    r = client.get("/rest/getLyricsBySongId", params={"id": TRACK_ID, "f": "json"})
    assert r.status_code == 200
    error = r.json()["subsonic-response"]["error"]
    assert error["code"] == 0
    assert "LRCLIB" in error["message"]


def test_settings_from_the_environment(services: Services, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UT_LYRICS_NOT_FOUND_RETRY_DAYS", "3")
    monkeypatch.setenv("UT_LYRICS_TIMEOUT_S", "2.5")
    built = build_lyrics_service(services)
    assert built.settings.lyrics_not_found_retry_days == 3
    assert built.settings.lyrics_timeout_s == 2.5
    assert built.db is services.db
    explicit = LyricsSettings(lyrics_burst=4)
    assert build_lyrics_service(services, explicit).settings is explicit
    monkeypatch.setenv("UT_LYRICS_RATE_PER_S", "0")
    with pytest.raises(ValueError, match="greater than 0"):
        LyricsSettings()
