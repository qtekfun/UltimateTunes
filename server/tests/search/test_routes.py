# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`search3` and `/ut/v1/search` end to end, checked against the contracts' schemas."""

from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import jsonschema  # type: ignore[import-untyped]  # dev-only, via schemathesis
import pytest
import yaml  # type: ignore[import-untyped]  # dev-only, via schemathesis
from fastapi.testclient import TestClient

from tests.search.conftest import (
    DUSK,
    LANTERNS,
    LIGHTHOUSE,
    LOW_TIDE,
    TIDEWATER,
    USER,
    seed_library,
)
from ultimatetunes.app import create_app
from ultimatetunes.core.authn import Principal
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.services import build_services
from ultimatetunes.db import migrate
from ultimatetunes.search.fake import FakeMusicCatalog
from ultimatetunes.settings import Settings

OPENAPI = Path(__file__).resolve().parents[3] / "contracts" / "openapi"
MIGRATIONS = Path(__file__).resolve().parents[3] / "contracts" / "db" / "migrations"


def schema_validator(name: str, component: str) -> jsonschema.Draft202012Validator:
    spec = yaml.safe_load((OPENAPI / name).read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator({**spec, "$ref": f"#/components/schemas/{component}"})


SEARCH3 = schema_validator("opensubsonic-subset.yaml", "Search3Response")
SEARCH = schema_validator("ut-v1.yaml", "SearchResult")


class Ana:
    principal = Principal(USER, "ana", "admin")

    def authenticate_subsonic(
        self, params: Mapping[str, Sequence[str]], ip: str | None
    ) -> Principal:
        return self.principal

    def authenticate_api_key(
        self, header: str | None, query: str | None, ip: str | None
    ) -> Principal:
        return self.principal


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    clock = FakeClock()
    conn = migrate.connect(settings.database_file)
    migrate.migrate(conn, MIGRATIONS, clock)
    conn.close()
    services = build_services(settings, clock)
    services.catalog = FakeMusicCatalog()
    services.authenticator = Ana()
    seed_library(services.db)
    with TestClient(create_app(services=services)) as test_client:
        yield test_client


def search3(client: TestClient, **params: str) -> dict[str, Any]:
    r = client.get("/rest/search3", params={"f": "json", "apiKey": "utk_x", **params})
    assert r.status_code == 200
    body: dict[str, Any] = r.json()
    SEARCH3.validate(body)
    result: dict[str, Any] = body["subsonic-response"]
    return result


def test_search3_json(client: TestClient) -> None:
    body = search3(client, query="lanterns")
    assert body["status"] == "ok"
    result = body["searchResult3"]
    assert [a["id"] for a in result["artist"]] == [LANTERNS]
    assert [a["id"] for a in result["album"]][-1] == DUSK
    songs = result["song"]
    assert [s["id"] for s in songs] == [
        LIGHTHOUSE,
        LOW_TIDE,
        TIDEWATER,
        "yt:Rb8Tn3ZcYv0",
        "yt:Qx7Lm2pZ0aB",
    ]
    lighthouse = songs[0]
    assert lighthouse["coverArt"].startswith("al-")
    assert lighthouse["starred"] == "2026-10-01T10:00:00.000Z"
    assert lighthouse["playCount"] == 14
    assert lighthouse["duration"] == 214
    assert lighthouse["replayGain"] == {"trackGain": -7.12, "trackPeak": 0.988}
    assert lighthouse["suffix"] == "opus"
    external = songs[-1]
    assert external == {
        "id": "yt:Qx7Lm2pZ0aB",
        "parent": "ytalbum:MPREb_k3Vd9QmT2xL",
        "isDir": False,
        "title": "Paper Moons (Live)",
        "album": "Lanterns at Dusk",
        "artist": "The Paper Lanterns",
        "track": 4,
        "year": 2024,
        "coverArt": "yt:Qx7Lm2pZ0aB",
        "duration": 262,
        "albumId": "ytalbum:MPREb_k3Vd9QmT2xL",
        "artistId": "ytartist:UCq8XbV1r0LwZ5mN3tYp7kQe",
        "type": "music",
        "mediaType": "song",
        "isVideo": False,
        "musicBrainzId": "",
        "genres": [],
        "artists": [{"id": "ytartist:UCq8XbV1r0LwZ5mN3tYp7kQe", "name": "The Paper Lanterns"}],
        "displayArtist": "The Paper Lanterns",
        "albumArtists": [{"id": "ytartist:UCq8XbV1r0LwZ5mN3tYp7kQe", "name": "The Paper Lanterns"}],
        "displayAlbumArtist": "The Paper Lanterns",
        "replayGain": {},
    }


def test_search3_external_albums_and_artists(client: TestClient) -> None:
    result = search3(client, query="neon")["searchResult3"]
    assert result["artist"] == [
        {
            "id": "ytartist:UCn4HbR7oQ2sLx9TzV0eWm3K",
            "name": "Neon Harbor",
            "coverArt": "ytartist:UCn4HbR7oQ2sLx9TzV0eWm3K",
        }
    ]
    (album,) = result["album"]
    assert album["id"] == "ytalbum:MPREb_Hn2Vq8Lr5Tz"
    assert album["coverArt"] == "ytalbum:MPREb_Hn2Vq8Lr5Tz"
    assert album["created"] == "2026-10-12T08:00:00.000Z"
    assert (album["songCount"], album["duration"], album["year"]) == (0, 0, 2025)


def test_search3_xml_and_form_post(client: TestClient) -> None:
    r = client.get("/rest/search3.view", params={"apiKey": "utk_x", "query": "bloom"})
    assert r.status_code == 200
    assert '<song id="yt:Hm3Vx8Nq2Lp"' in r.text
    assert '<album id="ytalbum:MPREb_Hn2Vq8Lr5Tz"' in r.text
    form = client.post(
        "/rest/search3", data={"f": "json", "apiKey": "utk_x", "query": "", "songCount": "1"}
    )
    songs = form.json()["subsonic-response"]["searchResult3"]["song"]
    assert [s["id"] for s in songs] == [LIGHTHOUSE]


def test_search3_empty_result_has_empty_lists(client: TestClient) -> None:
    result = search3(client, query="zzzz")["searchResult3"]
    assert result == {"artist": [], "album": [], "song": []}


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({}, 10),
        ({"query": "x", "songCount": "-1"}, 0),
        ({"query": "x", "albumOffset": "-5"}, 0),
        ({"query": "x", "artistCount": "lots"}, 0),
    ],
)
def test_search3_parameter_errors(client: TestClient, params: dict[str, str], code: int) -> None:
    body = search3(client, **params)
    assert body["status"] == "failed"
    assert body["error"]["code"] == code


def test_search3_caps_counts(client: TestClient) -> None:
    result = search3(client, query="", songCount="100000")["searchResult3"]
    assert len(result["song"]) == 3


def test_ut_v1_search(client: TestClient) -> None:
    r = client.get("/ut/v1/search", params={"q": "lanterns", "limit": 5})
    assert r.status_code == 200
    body = r.json()
    SEARCH.validate(body)
    assert body["query"] == "lanterns"
    assert body["artists"] == [
        {
            "id": LANTERNS,
            "name": "The Paper Lanterns",
            "coverArt": f"ar-{LANTERNS}",
            "isExternal": False,
        }
    ]
    tracks = body["tracks"]
    assert [(t["id"], t["isExternal"], t["libraryState"]) for t in tracks] == [
        (LIGHTHOUSE, False, "ready"),
        (LOW_TIDE, False, "ready"),
        (TIDEWATER, False, "ready"),
        ("yt:Rb8Tn3ZcYv0", True, "pending"),
        ("yt:Qx7Lm2pZ0aB", True, None),
    ]
    assert tracks[0]["durationSec"] == 214
    assert tracks[-1]["coverArt"] == "yt:Qx7Lm2pZ0aB"
    assert tracks[-1]["albumId"] == "ytalbum:MPREb_k3Vd9QmT2xL"
    album = body["albums"][-1]
    assert album == {
        "id": DUSK,
        "name": "Lanterns at Dusk",
        "artist": "The Paper Lanterns",
        "artistId": LANTERNS,
        "year": 2023,
        "songCount": 1,
        "coverArt": f"al-{DUSK}",
        "isExternal": False,
    }


def test_ut_v1_search_external_items(client: TestClient) -> None:
    body = client.get("/ut/v1/search", params={"q": "bloom"}).json()
    SEARCH.validate(body)
    assert body["albums"] == [
        {
            "id": "ytalbum:MPREb_Hn2Vq8Lr5Tz",
            "name": "Static Bloom",
            "artist": "Neon Harbor",
            "artistId": "ytartist:UCn4HbR7oQ2sLx9TzV0eWm3K",
            "year": 2025,
            "songCount": None,
            "coverArt": "ytalbum:MPREb_Hn2Vq8Lr5Tz",
            "isExternal": True,
        }
    ]
    neon = client.get("/ut/v1/search", params={"q": "neon"}).json()
    assert neon["artists"] == [
        {
            "id": "ytartist:UCn4HbR7oQ2sLx9TzV0eWm3K",
            "name": "Neon Harbor",
            "coverArt": "ytartist:UCn4HbR7oQ2sLx9TzV0eWm3K",
            "isExternal": True,
        }
    ]


def test_ut_v1_search_library_only(client: TestClient) -> None:
    body = client.get("/ut/v1/search", params={"q": "lanterns", "external": "false"}).json()
    assert all(not t["isExternal"] for t in body["tracks"])


@pytest.mark.parametrize(
    "params", [{}, {"q": ""}, {"q": "x" * 201}, {"q": "x", "limit": 0}, {"q": "x", "limit": 51}]
)
def test_ut_v1_search_validation(client: TestClient, params: dict[str, object]) -> None:
    r = client.get("/ut/v1/search", params=params)
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_parameter"
