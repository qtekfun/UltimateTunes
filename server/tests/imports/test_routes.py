# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`/ut/v1/imports` end to end: upload or URL → background run → match report → playlist.

The TestClient returns once the response's background tasks finished, so each `POST` below
comes back after the import ran; the `GET` then shows the finished match report.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.imports.conftest import (
    OTHER_USER,
    USER,
    AllowAll,
    FixtureCatalog,
    fixture_bytes,
    schema_validator,
)
from ultimatetunes.app import create_app
from ultimatetunes.core.authn import Principal
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.services import Services
from ultimatetunes.errors import InvalidApiKey
from ultimatetunes.imports.files import MAX_FILE_BYTES
from ultimatetunes.search.fake import PLAYLIST_ID

IMPORT = schema_validator("Import")
IMPORT_LIST = schema_validator("ImportList")
PROBLEM = schema_validator("Problem")


def upload(
    client: TestClient, data: bytes, fmt: str, *, filename: str = "x.csv", name: str | None = None
) -> Any:
    fields = {"format": fmt} if name is None else {"format": fmt, "name": name}
    return client.post("/ut/v1/imports", files={"file": (filename, data, "text/csv")}, data=fields)


def problem(r: Any, status: int, code: str) -> None:
    assert r.status_code == status, r.text
    assert r.headers["content-type"] == "application/problem+json"
    PROBLEM.validate(r.json())
    assert r.json()["code"] == code


def rows(services: Services, sql: str, params: tuple[object, ...] = ()) -> list[dict[str, Any]]:
    with services.db.read() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def test_a_50_track_playlist_imports_with_a_match_report(
    client: TestClient, services: Services
) -> None:
    r = upload(client, fixture_bytes("road_trip_50.csv"), "csv", filename="Road_Trip_50.csv")
    assert r.status_code == 202, r.text
    created = r.json()
    IMPORT.validate(created)
    assert r.headers["location"] == f"/ut/v1/imports/{created['id']}"
    assert created["state"] == "queued"
    assert created["name"] == "Road Trip 50"
    assert created["total"] == 50
    assert created["sourceUrl"] is None
    assert len(created["items"]) == 50

    report = client.get(f"/ut/v1/imports/{created['id']}").json()
    IMPORT.validate(report)
    assert report["state"] == "done"
    assert (report["total"], report["matched"], report["notFound"]) == (50, 44, 6)
    assert report["progress"] == 1
    assert report["finishedAt"] is not None
    items = report["items"]
    assert [i["position"] for i in items] == list(range(50))
    not_found = [i["position"] for i in items if i["state"] == "not_found"]
    assert not_found == [44, 45, 46, 47, 48, 49]
    matched = [i for i in items if i["state"] == "matched"]
    assert all(i["matchScore"] >= 0.7 for i in matched)
    assert all(
        i["track"]["isExternal"] and i["track"]["libraryState"] == "pending" for i in matched
    )
    # Song 0 has an "Official Video" decoy: the album track wins.
    catalog = FixtureCatalog()
    assert items[0]["track"]["id"] == f"yt:{catalog.songs[0].video_id}"
    assert items[0]["track"]["title"] == catalog.songs[0].title
    # The variants still match: feat. in the title, 2 s longer, other casing, no album/duration.
    assert [items[p]["state"] for p in (40, 41, 42, 43)] == ["matched"] * 4
    assert items[40]["sourceTitle"].endswith("(feat. Kestrel Bay)")
    assert items[43]["sourceDurationSec"] is None

    playlist = rows(services, "SELECT * FROM playlists WHERE id = ?", (report["playlistId"],))
    assert playlist[0]["owner_id"] == USER
    assert playlist[0]["name"] == "Road Trip 50"
    entries = rows(
        services,
        "SELECT p.position, a.alias FROM playlist_tracks p JOIN track_aliases a"
        " ON a.track_id = p.track_id WHERE p.playlist_id = ? ORDER BY p.position",
        (report["playlistId"],),
    )
    assert [e["position"] for e in entries] == list(range(44))
    assert [e["alias"] for e in entries] == [i["track"]["id"] for i in matched]
    jobs = rows(services, "SELECT state, priority, requested_by FROM jobs")
    assert len(jobs) == 44
    assert {(j["state"], j["priority"], j["requested_by"]) for j in jobs} == {("queued", 10, USER)}
    isrcs = rows(
        services, "SELECT position, source_isrc FROM import_items WHERE source_isrc IS NOT NULL"
    )
    assert [i["position"] for i in isrcs] == [p for p in range(50) if p % 7 == 0]


def test_a_youtube_music_url_imports_the_playlist(
    client: TestClient, services: Services, catalog: FixtureCatalog
) -> None:
    url = f"https://music.youtube.com/playlist?list={PLAYLIST_ID}"
    r = client.post("/ut/v1/imports", json={"url": url})
    assert r.status_code == 202, r.text
    IMPORT.validate(r.json())
    assert r.json()["source"] == "ytmusic"
    assert r.json()["sourceUrl"] == url
    report = client.get(r.headers["location"]).json()
    IMPORT.validate(report)
    assert report["name"] == "Road Trip (fake)"
    assert (report["state"], report["total"], report["matched"]) == ("done", 3, 3)
    assert [i["matchScore"] for i in report["items"]] == [1.0, 1.0, 1.0]
    assert [i["track"]["id"] for i in report["items"]] == [
        "yt:Wq5Jd7HsKe2",
        "yt:Tz9Kd4Wb7Rc",
        "yt:Qx7Lm2pZ0aB",
    ]
    assert "search_songs" not in catalog.calls
    assert "track" not in catalog.calls


def test_the_name_given_wins_and_a_library_track_shows_as_ready(
    client: TestClient, services: Services, clock: FakeClock
) -> None:
    url = f"https://www.youtube.com/watch?v=Wq5Jd7HsKe2&list={PLAYLIST_ID}"
    first = client.post("/ut/v1/imports", json={"url": url, "name": "Mine"}).json()
    with services.db.transaction() as conn:
        conn.execute("UPDATE tracks SET status = 'ready' WHERE yt_video_id = 'Wq5Jd7HsKe2'")
    report = client.get(f"/ut/v1/imports/{first['id']}").json()
    IMPORT.validate(report)
    assert report["name"] == "Mine"
    ready = report["items"][0]["track"]
    assert (ready["isExternal"], ready["libraryState"]) == (False, "ready")
    assert ready["id"] != "yt:Wq5Jd7HsKe2"
    assert ready["coverArt"] == ""
    # A second import of the same playlist reuses the tracks and jobs.
    client.post("/ut/v1/imports", json={"url": url})
    assert len(rows(services, "SELECT id FROM tracks")) == 3
    assert len(rows(services, "SELECT id FROM jobs")) == 3
    assert len(rows(services, "SELECT id FROM playlists")) == 2


def test_exportify_csv(client: TestClient, catalog: FixtureCatalog) -> None:
    r = upload(client, fixture_bytes("exportify.csv"), "exportify_csv", filename="Mix.csv")
    assert r.status_code == 202, r.text
    report = client.get(r.headers["location"]).json()
    IMPORT.validate(report)
    assert report["source"] == "exportify_csv"
    assert [i["state"] for i in report["items"]] == ["matched", "matched", "not_found"]
    assert report["items"][0]["sourceArtist"] == "Marisol Vega; Guest Singer"
    assert report["items"][0]["sourceDurationSec"] == 209


def test_spotify_json_picks_the_named_playlist(client: TestClient, services: Services) -> None:
    data = fixture_bytes("spotify_playlists.json")
    r = upload(client, data, "spotify_json", filename="Playlist1.json")
    problem(r, 400, "invalid_parameter")
    assert "2 playlists" in r.json()["detail"]
    r = upload(client, data, "spotify_json", filename="Playlist1.json", name="road trip")
    assert r.status_code == 202, r.text
    report = client.get(r.headers["location"]).json()
    assert report["name"] == "road trip"
    assert (report["total"], report["matched"]) == (2, 2)


@pytest.mark.parametrize(
    "url",
    [
        "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
        "https://music.youtube.com/watch?v=Wq5Jd7HsKe2",
        "https://evil.example/playlist?list=PLx",
        "file:///etc/passwd?list=PLx9Kd2Lm4Qp",
        "https://music.youtube.com:8443/playlist?list=PLx9Kd2Lm4Qp",
    ],
)
def test_unsupported_urls(client: TestClient, url: str) -> None:
    problem(client.post("/ut/v1/imports", json={"url": url}), 400, "unsupported_url")


@pytest.mark.parametrize(
    ("kwargs", "status", "code"),
    [
        ({"json": {"name": "no url"}}, 400, "invalid_parameter"),
        (
            {"content": b"not json", "headers": {"content-type": "application/json"}},
            400,
            "invalid_parameter",
        ),
        (
            {"content": b"url=x", "headers": {"content-type": "text/plain"}},
            400,
            "invalid_parameter",
        ),
        (
            {"content": b"{}" + b" " * 20000, "headers": {"content-type": "application/json"}},
            413,
            "payload_too_large",
        ),
    ],
)
def test_bad_json_requests(
    client: TestClient, kwargs: dict[str, Any], status: int, code: str
) -> None:
    problem(client.post("/ut/v1/imports", **kwargs), status, code)


def test_upload_limits(client: TestClient) -> None:
    problem(
        upload(client, b"title,artist\n" + b"a" * MAX_FILE_BYTES, "csv"), 413, "payload_too_large"
    )
    problem(upload(client, b"title,artist\n\xff\xfe,x\n", "csv"), 400, "invalid_parameter")
    many = b"title,artist\n" + b"t,a\n" * 5001
    problem(upload(client, many, "csv"), 413, "payload_too_large")
    problem(upload(client, b"title,artist\nt,a\n", "xlsx"), 400, "invalid_parameter")
    problem(upload(client, b"title\nt\n", "csv"), 400, "invalid_parameter")
    long_name = "n" * 201
    problem(upload(client, b"title,artist\nt,a\n", "csv", name=long_name), 400, "invalid_parameter")
    r = client.post("/ut/v1/imports", data={"format": "csv"}, files={"other": ("x", b"y")})
    problem(r, 400, "invalid_parameter")
    r = client.post(
        "/ut/v1/imports",
        content=b"--b\r\nbroken",
        headers={"content-type": "multipart/form-data; boundary=b"},
    )
    problem(r, 400, "invalid_parameter")
    two = [("file", ("a.csv", b"title,artist\nt,a\n")), ("file", ("b.csv", b"x"))]
    problem(
        client.post("/ut/v1/imports", data={"format": "csv"}, files=two), 400, "invalid_parameter"
    )
    r = client.post("/ut/v1/imports", files=[("format", ("f", b"csv"))])
    problem(r, 400, "invalid_parameter")
    assert "text field" in r.json()["detail"]

    def chunks() -> Iterator[bytes]:
        for _ in range(20):
            yield b"x" * 65536

    r = client.post(
        "/ut/v1/imports",
        content=chunks(),
        headers={"content-type": "multipart/form-data; boundary=b"},
    )
    problem(r, 413, "payload_too_large")
    r = client.post(
        "/ut/v1/imports",
        content=b"x",
        headers={"content-type": "multipart/form-data; boundary=b", "content-length": "9999999"},
    )
    problem(r, 413, "payload_too_large")


def test_imports_are_per_user_and_listed_newest_first(
    client: TestClient, services: Services, clock: FakeClock
) -> None:
    ids = []
    for n in range(3):
        r = upload(client, b"title,artist\nUnheard,Nobody\n", "csv", name=f"n{n}")
        ids.append(r.json()["id"])
        clock.advance(1)
    listed = client.get("/ut/v1/imports", params={"limit": 2}).json()
    IMPORT_LIST.validate(listed)
    assert [i["id"] for i in listed["imports"]] == [ids[2], ids[1]]
    assert "items" not in listed["imports"][0]
    rest = client.get("/ut/v1/imports", params={"limit": 2, "offset": 2}).json()
    assert [i["id"] for i in rest["imports"]] == [ids[0]]
    problem(client.get("/ut/v1/imports", params={"limit": 0}), 400, "invalid_parameter")
    with services.db.transaction() as conn:
        conn.execute("UPDATE imports SET user_id = ? WHERE id = ?", (OTHER_USER, ids[0]))
    problem(client.get(f"/ut/v1/imports/{ids[0]}"), 404, "not_found")
    problem(client.get("/ut/v1/imports/not-a-uuid"), 404, "not_found")


def test_three_running_imports_at_most(client: TestClient, services: Services) -> None:
    for n in range(3):
        upload(client, b"title,artist\nUnheard,Nobody\n", "csv", name=f"n{n}")
    with services.db.transaction() as conn:
        conn.execute("UPDATE imports SET state = 'matching'")
    problem(upload(client, b"title,artist\nt,a\n", "csv"), 409, "conflict")


def test_a_stale_import_is_resumed_when_read(
    client: TestClient, services: Services, clock: FakeClock
) -> None:
    created = upload(client, fixture_bytes("exportify.csv"), "exportify_csv").json()
    with services.db.transaction() as conn:
        conn.execute(
            "UPDATE imports SET state = 'matching', playlist_id = NULL, matched_items = 0,"
            " not_found_items = 0, finished_at = NULL WHERE id = ?",
            (created["id"],),
        )
        conn.execute("UPDATE import_items SET state = 'pending', track_id = NULL")
        conn.execute("DELETE FROM playlists")
    # Fresh: left alone (a runner may still be on it).
    assert client.get(f"/ut/v1/imports/{created['id']}").json()["state"] == "matching"
    clock.advance(121)
    assert client.get("/ut/v1/imports").json()["imports"][0]["state"] == "matching"
    report = client.get(f"/ut/v1/imports/{created['id']}").json()
    assert (report["state"], report["matched"], report["notFound"]) == ("done", 2, 1)
    assert len(rows(services, "SELECT id FROM playlists")) == 1


class Deny(AllowAll):
    def authenticate_api_key(
        self, header_key: str | None, query_key: str | None, client_ip: str | None
    ) -> Principal:
        raise InvalidApiKey()


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/ut/v1/imports"),
        ("POST", "/ut/v1/imports"),
        ("GET", "/ut/v1/imports/0199d6a2-4c1e-7b3a-9f10-2a6c8e017001"),
    ],
)
def test_every_route_needs_an_api_key(services: Services, method: str, path: str) -> None:
    services.authenticator = Deny()
    with TestClient(create_app(services=services)) as client:
        r = client.request(
            method, path, json={"url": "https://music.youtube.com/playlist?list=PLx"}
        )
        with services.db.read() as conn:
            assert conn.execute("SELECT COUNT(*) AS n FROM imports").scalar() == 0
    problem(r, 401, "invalid_api_key")
