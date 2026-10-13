# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`/ut/v1/radio` and `getSimilarSongs2` end to end, checked against the contracts' schemas."""

from collections.abc import Iterator
from typing import Any
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from tests.search.conftest import LANTERNS, LIGHTHOUSE, LOW_TIDE, seed_library
from tests.search.test_routes import MIGRATIONS, Ana, schema_validator
from ultimatetunes.app import create_app
from ultimatetunes.core.caller import current_bucket
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.services import build_services
from ultimatetunes.db import migrate
from ultimatetunes.errors import UpstreamUnavailable
from ultimatetunes.radio.service import radio_settings
from ultimatetunes.search.catalog import CatalogTrack
from ultimatetunes.search.fake import FakeMusicCatalog
from ultimatetunes.settings import Settings

SIMILAR = schema_validator("opensubsonic-subset.yaml", "GetSimilarSongs2Response")
RADIO = schema_validator("ut-v1.yaml", "Radio")
LISTEN_NOW = schema_validator("ut-v1.yaml", "ListenNow")
# `/ut/v1/recommendations` is an additive endpoint not yet in the contract (proposal in
# docs/recommendations.md); its items are the contract's `TrackItem`, which is checked here.
TRACK_ITEM = schema_validator("ut-v1.yaml", "TrackItem")
XMLNS = "{http://subsonic.org/restapi}"


@pytest.fixture
def catalog() -> FakeMusicCatalog:
    return FakeMusicCatalog()


@pytest.fixture
def client(settings: Settings, catalog: FakeMusicCatalog) -> Iterator[TestClient]:
    clock = FakeClock()
    conn = migrate.connect(settings.database_file)
    migrate.migrate(conn, MIGRATIONS, clock)
    conn.close()
    services = build_services(settings, clock)
    services.catalog = catalog
    services.authenticator = Ana()
    seed_library(services.db)
    with TestClient(create_app(services=services)) as test_client:
        yield test_client


def similar(client: TestClient, **params: str) -> dict[str, Any]:
    r = client.get("/rest/getSimilarSongs2", params={"f": "json", "apiKey": "utk_x", **params})
    assert r.status_code == 200
    body: dict[str, Any] = r.json()
    SIMILAR.validate(body)
    result: dict[str, Any] = body["subsonic-response"]
    return result


def song_ids(result: dict[str, Any]) -> list[str]:
    return [s["id"] for s in result["similarSongs2"]["song"]]


# ---------------------------------------------------------------------- /ut/v1/radio


def test_radio(client: TestClient) -> None:
    r = client.get("/ut/v1/radio", params={"seed": "yt:Qx7Lm2pZ0aB"})
    assert r.status_code == 200
    body = r.json()
    RADIO.validate(body)
    assert body["seed"]["id"] == "yt:Qx7Lm2pZ0aB"
    assert body["seed"]["isExternal"] is True
    assert body["seed"]["libraryState"] is None
    items = body["items"]
    assert [(i["id"], i["isExternal"], i["libraryState"]) for i in items] == [
        (LOW_TIDE, False, "ready"),
        ("yt:Rb8Tn3ZcYv0", True, "pending"),
        (LIGHTHOUSE, False, "ready"),
        ("yt:Hm3Vx8Nq2Lp", True, None),
        ("yt:Tz9Kd4Wb7Rc", True, "pending"),
        ("yt:Pa6Ye1Uo3Gs", True, None),
    ]
    assert items[0]["coverArt"].startswith("al-")
    assert items[3]["coverArt"] == "yt:Hm3Vx8Nq2Lp"
    assert items[3]["albumId"] == "ytalbum:MPREb_Hn2Vq8Lr5Tz"


def test_radio_from_a_library_seed_with_limit(client: TestClient) -> None:
    r = client.get("/ut/v1/radio", params={"seed": LIGHTHOUSE, "limit": "2"})
    assert r.status_code == 200
    body = r.json()
    RADIO.validate(body)
    assert body["seed"]["id"] == LIGHTHOUSE
    assert body["seed"]["libraryState"] == "ready"
    assert [i["id"] for i in body["items"]] == [LOW_TIDE, "yt:Rb8Tn3ZcYv0"]


@pytest.mark.parametrize(
    ("params", "status", "code"),
    [
        ({"seed": "ytalbum:MPREb_k3Vd9QmT2xL"}, 400, "invalid_id"),
        ({"seed": "ytartist:UCq8XbV1r0LwZ5mN3tYp7kQe"}, 400, "invalid_id"),
        ({"seed": "yt:Zz0Zz0Zz0Zz"}, 404, "not_found"),
        ({"seed": LANTERNS}, 404, "not_found"),
    ],
)
def test_radio_errors(client: TestClient, params: dict[str, str], status: int, code: str) -> None:
    r = client.get("/ut/v1/radio", params=params)
    assert r.status_code == status
    assert r.json()["code"] == code


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"seed": ""},
        {"seed": "y" * 81},
        {"seed": LIGHTHOUSE, "limit": "0"},
        {"seed": LIGHTHOUSE, "limit": "101"},
    ],
)
def test_radio_parameter_errors(client: TestClient, params: dict[str, str]) -> None:
    assert client.get("/ut/v1/radio", params=params).status_code == 400


def test_radio_upstream_failure(client: TestClient, catalog: FakeMusicCatalog) -> None:
    catalog.fail_with = UpstreamUnavailable()
    r = client.get("/ut/v1/radio", params={"seed": "yt:Qx7Lm2pZ0aB"})
    assert r.status_code == 502
    assert r.json()["code"] == "upstream_unavailable"


def test_radio_switched_off(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UT_RADIO", "false")
    radio_settings.cache_clear()
    try:
        r = client.get("/ut/v1/radio", params={"seed": "yt:Qx7Lm2pZ0aB"})
    finally:
        radio_settings.cache_clear()
    assert r.status_code == 409
    assert r.json()["code"] == "feature_disabled"


# ---------------------------------------------------------------------- getSimilarSongs2


def test_similar_songs_leave_the_song_seed_out(client: TestClient) -> None:
    result = similar(client, id="yt:Qx7Lm2pZ0aB")
    assert result["status"] == "ok"
    assert song_ids(result) == [
        LOW_TIDE,
        "yt:Rb8Tn3ZcYv0",
        LIGHTHOUSE,
        "yt:Hm3Vx8Nq2Lp",
        "yt:Tz9Kd4Wb7Rc",
        "yt:Pa6Ye1Uo3Gs",
    ]
    songs = result["similarSongs2"]["song"]
    lighthouse = songs[2]
    # Per-user fields of the caller, file fields of the archive.
    assert lighthouse["starred"] == "2026-10-01T10:00:00.000Z"
    assert lighthouse["playCount"] == 14
    assert lighthouse["suffix"] == "opus"
    assert songs[3]["coverArt"] == "yt:Hm3Vx8Nq2Lp"
    assert songs[3]["replayGain"] == {}


def test_similar_songs_of_an_artist_start_with_its_top_song(client: TestClient) -> None:
    result = similar(client, id="ytartist:UCn4HbR7oQ2sLx9TzV0eWm3K", count="3")
    assert song_ids(result) == ["yt:Hm3Vx8Nq2Lp", LOW_TIDE, "yt:Rb8Tn3ZcYv0"]
    library_artist = similar(client, id=LANTERNS, count="2")
    assert song_ids(library_artist) == [LOW_TIDE, "yt:Rb8Tn3ZcYv0"]


def test_similar_songs_count_zero_never_calls_the_catalog(
    client: TestClient, catalog: FakeMusicCatalog
) -> None:
    assert song_ids(similar(client, id=LIGHTHOUSE, count="0")) == []
    assert song_ids(similar(client, id="ytartist:UCn4HbR7oQ2sLx9TzV0eWm3K", count="0")) == []
    assert catalog.calls == []
    assert similar(client, id="ytalbum:bad id", count="0")["error"]["code"] == 70


def test_similar_songs_count(client: TestClient) -> None:
    assert song_ids(similar(client, id=LIGHTHOUSE, count="1")) == [LOW_TIDE]
    assert len(song_ids(similar(client, id=LIGHTHOUSE, count="100000"))) == 6


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({}, 10),
        ({"id": ""}, 10),
        ({"id": LIGHTHOUSE, "count": "-1"}, 0),
        ({"id": LIGHTHOUSE, "count": "many"}, 0),
        ({"id": "ytalbum:MPREb_k3Vd9QmT2xL"}, 70),
        ({"id": "yt:bad"}, 70),
        ({"id": "yt:Zz0Zz0Zz0Zz"}, 70),
    ],
)
def test_similar_songs_errors(client: TestClient, params: dict[str, str], code: int) -> None:
    result = similar(client, **params)
    assert result["status"] == "failed"
    assert result["error"]["code"] == code


def test_similar_songs_xml_and_form_post(client: TestClient) -> None:
    r = client.post(
        "/rest/getSimilarSongs2.view",
        data={"apiKey": "utk_x", "id": "yt:Qx7Lm2pZ0aB", "count": "2"},
    )
    assert r.status_code == 200
    root = ET.fromstring(r.text)  # noqa: S314 - our own response
    assert root.get("status") == "ok"
    songs = root.findall(f"{XMLNS}similarSongs2/{XMLNS}song")
    assert [s.get("id") for s in songs] == [LOW_TIDE, "yt:Rb8Tn3ZcYv0"]
    assert songs[0].find(f"{XMLNS}replayGain") is not None


def test_similar_songs_without_songs_is_an_empty_list(
    client: TestClient, catalog: FakeMusicCatalog
) -> None:
    async def radio(video_id: str, limit: int) -> list[Any]:
        return [catalog.tracks[video_id]]

    catalog.radio = radio  # type: ignore[method-assign]
    result = similar(client, id="yt:Qx7Lm2pZ0aB")
    assert result["similarSongs2"] == {"song": []}


# ---------------------------------------------------------------------- /ut/v1/listen-now


def test_listen_now(client: TestClient) -> None:
    r = client.get("/ut/v1/listen-now")
    assert r.status_code == 200
    body = r.json()
    LISTEN_NOW.validate(body)
    assert [s["id"] for s in body["mostPlayed"]] == [LIGHTHOUSE]
    assert [s["seedId"] for s in body["favouriteRadios"]] == [LIGHTHOUSE]


def test_ut_catalog_lookups_are_charged_to_the_caller(
    client: TestClient, catalog: FakeMusicCatalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str | None] = []
    real = catalog.radio

    async def radio(video_id: str, limit: int) -> list[CatalogTrack]:
        seen.append(current_bucket())
        return await real(video_id, limit)

    monkeypatch.setattr(catalog, "radio", radio)
    assert client.get("/ut/v1/radio", params={"seed": "yt:Qx7Lm2pZ0aB"}).status_code == 200
    assert similar(client, id="yt:Qx7Lm2pZ0aB")["status"] == "ok"
    assert seen == [Ana.principal.user_id, Ana.principal.user_id]


# ---------------------------------------------------------------------- /ut/v1/recommendations


def _check_items(body: dict[str, Any]) -> None:
    for item in body["recommendedForYou"]:
        TRACK_ITEM.validate(item)
    for shelf in body["becauseYouPlayed"]:
        TRACK_ITEM.validate(shelf["seed"])
        for item in shelf["items"]:
            TRACK_ITEM.validate(item)


def test_recommendations(client: TestClient) -> None:
    r = client.get("/ut/v1/recommendations")
    assert r.status_code == 200
    body = r.json()
    _check_items(body)
    # ana's only seed is Lighthouse Keeper (played and starred).
    assert [shelf["seed"]["id"] for shelf in body["becauseYouPlayed"]] == [LIGHTHOUSE]
    shelf = body["becauseYouPlayed"][0]
    assert [i["id"] for i in shelf["items"]] == [
        LOW_TIDE,
        "yt:Rb8Tn3ZcYv0",
        "yt:Qx7Lm2pZ0aB",
        "yt:Hm3Vx8Nq2Lp",
        "yt:Tz9Kd4Wb7Rc",
        "yt:Pa6Ye1Uo3Gs",
    ]
    assert shelf["items"][1]["libraryState"] == "pending"
    assert [i["id"] for i in body["recommendedForYou"]] == [i["id"] for i in shelf["items"]]


def test_recommendations_limit(client: TestClient) -> None:
    r = client.get("/ut/v1/recommendations", params={"limit": "2"})
    assert r.status_code == 200
    body = r.json()
    _check_items(body)
    assert len(body["recommendedForYou"]) == 2
    assert all(len(shelf["items"]) <= 2 for shelf in body["becauseYouPlayed"])


@pytest.mark.parametrize("params", [{"limit": "0"}, {"limit": "51"}, {"limit": "many"}])
def test_recommendations_parameter_errors(client: TestClient, params: dict[str, str]) -> None:
    assert client.get("/ut/v1/recommendations", params=params).status_code == 400


def test_recommendations_switched_off(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UT_RECOMMENDATIONS", "false")
    radio_settings.cache_clear()
    try:
        r = client.get("/ut/v1/recommendations")
    finally:
        radio_settings.cache_clear()
    assert r.status_code == 409
    assert r.json()["code"] == "feature_disabled"


def test_recommendations_upstream_failure(client: TestClient, catalog: FakeMusicCatalog) -> None:
    catalog.fail_with = UpstreamUnavailable()
    r = client.get("/ut/v1/recommendations")
    assert r.status_code == 502
    assert r.json()["code"] == "upstream_unavailable"


def test_recommendations_are_charged_to_the_caller(
    client: TestClient, catalog: FakeMusicCatalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str | None] = []
    real = catalog.radio

    async def radio(video_id: str, limit: int) -> list[CatalogTrack]:
        seen.append(current_bucket())
        return await real(video_id, limit)

    monkeypatch.setattr(catalog, "radio", radio)
    assert client.get("/ut/v1/recommendations").status_code == 200
    assert seen == [Ana.principal.user_id]
