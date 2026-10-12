# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Contract checks with real data (PLAN T19).

Generated requests (`test_schemathesis.py`) rarely hit an id that exists, so this module
replays the endpoints that take ids with the invented library's real ids, the fake catalog's
`yt:` ids, and objects created on the way (a playlist, a star, a play queue, an import, a
download job). Every response goes through the same schemathesis conformance checks.

OpenSubsonic endpoints are called in JSON **and** XML: the XML must be exactly the JSON mapped
with the contract's XML rule (opensubsonic-subset.yaml, "XML mapping rule"), implemented here
independently of the server (`to_xml`). Elements are compared without order, since repeated
elements carry no order the rule promises (and `getRandomSongs` shuffles).
"""

import xml.etree.ElementTree as ET
from collections.abc import Iterator, Mapping
from typing import Any

import anyio
import pytest
import schemathesis
from schemathesis.schemas import BaseSchema

from tests.contract.harness import (
    API_KEY,
    APP,
    OPENAPI,
    SERVICES,
    TOKEN,
    USER_ID,
    SessionLifespan,
    library_ids,
)
from tests.contract.test_schemathesis import CHECKS
from ultimatetunes.library.songs import keep

XMLNS = "http://subsonic.org/restapi"
# Fake catalog ids (search/fake.py): a song with an album, its album, the fake playlist.
YT_SONG = "yt:Fk2Lp9QwXa1"
YT_OTHER = "yt:Hm3Vx8Nq2Lp"
YT_ALBUM = "ytalbum:MPREb_k3Vd9QmT2xL"
YT_PLAYLIST_URL = "https://music.youtube.com/playlist?list=PLfakeRoadTrip0123456789abcdefGH"

Canonical = tuple[str, tuple[tuple[str, str], ...], str, tuple[Any, ...]]


def _load(name: str) -> BaseSchema:
    schema = schemathesis.openapi.from_path(OPENAPI / name)
    schema.app = SessionLifespan(APP)
    return schema


SUBSONIC = _load("opensubsonic-subset.yaml")
UT = _load("ut-v1.yaml")
INTERNAL = _load("internal-worker.yaml")


# ---------------------------------------------------------------- the XML rule, independently


def _scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def to_xml(name: str, document: Mapping[str, Any]) -> ET.Element:
    """One JSON object as the element `name`, following the contract's mapping rule."""
    element = ET.Element(name)
    for key, value in document.items():
        if value is None:
            continue
        if name == "line" and key == "value":
            element.text = _scalar(value)
        elif isinstance(value, Mapping):
            element.append(to_xml(key, value))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, Mapping):
                    element.append(to_xml(key, item))
                else:
                    child = ET.SubElement(element, key)
                    child.text = _scalar(item)
        else:
            element.set(key, _scalar(value))
    return element


def canonical(element: ET.Element) -> Canonical:
    tag = element.tag.removeprefix("{" + XMLNS + "}")
    attrs = tuple(sorted(element.attrib.items()))
    if element.get("id", "").startswith("yt"):
        # An external item is "created" when it is rendered: the JSON and the XML call differ.
        attrs = tuple(a for a in attrs if a[0] != "created")
    text = (element.text or "").strip()
    return tag, attrs, text, tuple(sorted(canonical(child) for child in element))


def parse_xml(text: str) -> ET.Element:
    root = ET.fromstring(text)  # noqa: S314 - our own server's answer, in a test
    assert root.tag == "{" + XMLNS + "}subsonic-response", root.tag
    return root


# ---------------------------------------------------------------- calls


def call(schema: BaseSchema, method: str, path: str, **parts: Any) -> Any:
    """One explicit case through the conformance checks; the response."""
    case = schema[path][method].Case(**parts)
    return case.call_and_validate(checks=CHECKS)


def rest(endpoint: str, fmt: str, **params: Any) -> Any:
    query = {**params, "f": fmt, "apiKey": API_KEY}
    return call(SUBSONIC, "GET", f"/rest/{endpoint}", query=query)


def both(endpoint: str, **params: Any) -> dict[str, Any]:
    """The endpoint in JSON and in XML; asserts the XML is the JSON mapped by the rule and
    returns the JSON `subsonic-response`."""
    as_json = rest(endpoint, "json", **params)
    as_xml = rest(endpoint, "xml", **params)
    assert as_json.status_code == as_xml.status_code == 200
    body: dict[str, Any] = as_json.json()["subsonic-response"]
    expected = to_xml("subsonic-response", body)
    assert canonical(parse_xml(as_xml.text)) == canonical(expected), as_xml.text
    return body


def ok(endpoint: str, **params: Any) -> dict[str, Any]:
    body = both(endpoint, **params)
    assert body["status"] == "ok", body
    return body


@pytest.fixture(scope="module")
def ids() -> dict[str, str]:
    return library_ids()


# ---------------------------------------------------------------- OpenSubsonic, JSON and XML


@pytest.mark.parametrize(
    ("endpoint", "params"),
    [
        ("ping", {}),
        ("getLicense", {}),
        ("getOpenSubsonicExtensions", {}),
        ("tokenInfo", {}),
        ("getMusicFolders", {}),
        ("getArtists", {}),
        ("getAlbumList2", {"type": "alphabeticalByName", "size": 10}),
        ("getAlbumList2", {"type": "newest"}),
        # More than the library holds: every song, in a random order (compared without order).
        ("getRandomSongs", {"size": 50}),
        ("search3", {"query": "Lanterns"}),
        ("search3", {"query": ""}),
        ("getSimilarSongs2", {"id": YT_SONG, "count": 5}),
    ],
)
def test_endpoint_without_ids(endpoint: str, params: dict[str, Any]) -> None:
    ok(endpoint, **params)


@pytest.mark.parametrize(
    ("endpoint", "name"),
    [
        ("getArtist", "The Paper Lanterns"),
        ("getAlbum", "Harbour Lights"),
        ("getAlbum", "Salt & Ember"),
        ("getSong", "Lighthouse Keeper"),
        ("getSong", "Tidewater"),
        ("getSimilarSongs2", "Lighthouse Keeper"),
        ("getLyricsBySongId", "Lighthouse Keeper"),
    ],
)
def test_endpoint_with_a_library_id(endpoint: str, name: str, ids: dict[str, str]) -> None:
    both(endpoint, id=ids[name])


@pytest.mark.parametrize(
    ("endpoint", "item"),
    [("getSong", YT_SONG), ("getAlbum", YT_ALBUM), ("getSong", "0199d6a2-0000-7000-8000-0")],
)
def test_external_and_unknown_ids(endpoint: str, item: str) -> None:
    both(endpoint, id=item)


def test_an_unknown_id_is_error_70_in_both_formats() -> None:
    body = both("getSong", id="0199d6a2-4c1e-7b3a-9f10-2a6c8e01ffff")
    assert body["status"] == "failed"
    assert body["error"]["code"] == 70


def once(endpoint: str, fmt: str = "json", **params: Any) -> dict[str, Any]:
    """A call that changes state: made once (JSON or XML), its envelope `ok`."""
    response = rest(endpoint, fmt, **params)
    assert response.status_code == 200, response.text
    if fmt == "xml":
        root = parse_xml(response.text)
        assert root.get("status") == "ok", response.text
        return {"status": "ok"}
    body: dict[str, Any] = response.json()["subsonic-response"]
    assert body["status"] == "ok", body
    return body


def test_playlist_lifecycle(ids: dict[str, str]) -> None:
    created = once("createPlaylist", name="Contract mix", songId=ids["Tidewater"])
    playlist_id = created["playlist"]["id"]
    once("updatePlaylist", "xml", playlistId=playlist_id, songIdToAdd=ids["Brasas"])
    once("updatePlaylist", playlistId=playlist_id, comment="night")
    ok("getPlaylist", id=playlist_id)
    ok("getPlaylists")
    once("deletePlaylist", "xml", id=playlist_id)
    assert both("getPlaylist", id=playlist_id)["error"]["code"] == 70


def test_stars_scrobbles_and_the_play_queue(ids: dict[str, str]) -> None:
    once("star", id=ids["Lighthouse Keeper"], albumId=ids["Harbour Lights"])
    once("star", "xml", artistId=ids["Marisol Vega"])
    ok("getStarred2")
    once("scrobble", id=ids["Tidewater"], submission="true")
    once("savePlayQueue", id=[ids["Lighthouse Keeper"], ids["Tidewater"]], current=ids["Tidewater"])
    ok("getPlayQueue")
    once("unstar", "xml", id=ids["Lighthouse Keeper"], albumId=ids["Harbour Lights"])


@pytest.mark.parametrize("endpoint", ["stream", "download", "getCoverArt"])
def test_binary_endpoints_with_a_library_id(endpoint: str, ids: dict[str, str]) -> None:
    item = ids["Harbour Lights"] if endpoint == "getCoverArt" else ids["Lighthouse Keeper"]
    response = rest(endpoint, "json", id=item)
    assert response.status_code == 200
    assert response.content


def test_a_range_request_is_partial(ids: dict[str, str]) -> None:
    query = {"id": ids["Lighthouse Keeper"], "apiKey": API_KEY}
    response = call(SUBSONIC, "GET", "/rest/stream", query=query, headers={"Range": "bytes=0-9"})
    assert response.status_code == 206
    assert len(response.content) == 10


# ---------------------------------------------------------------- ut-v1


def ut(method: str, path: str, **parts: Any) -> Any:
    headers = {**parts.pop("headers", {}), "X-Api-Key": API_KEY}
    return call(UT, method, path, headers=headers, **parts)


def implemented(response: Any) -> Any:
    """A contract stub answers 501 until its owner task lands: skipped, not failed, so the
    check turns itself on with the implementation."""
    if response.status_code == 501:
        pytest.skip(f"not implemented yet: {response.request.method} {response.request.url}")
    return response


@pytest.mark.parametrize(
    ("path", "query"),
    [
        ("/ut/v1/server", {}),
        ("/ut/v1/me", {}),
        ("/ut/v1/keys", {}),
        ("/ut/v1/listen-now", {}),
        ("/ut/v1/search", {"q": "Lanterns"}),
        ("/ut/v1/radio", {"seed": YT_SONG}),
        ("/ut/v1/imports", {}),
    ],
)
def test_ut_v1_reads(path: str, query: dict[str, Any]) -> None:
    assert ut("GET", path, query=query).status_code == 200


def test_ut_v1_track_status_of_library_and_external_songs(ids: dict[str, str]) -> None:
    for item in (ids["Brasas"], YT_OTHER):
        response = implemented(ut("GET", "/ut/v1/tracks/{id}/status", path_parameters={"id": item}))
        assert response.status_code == 200, response.text


def test_ut_v1_radio_from_a_scanned_song_without_a_youtube_alias(ids: dict[str, str]) -> None:
    response = ut("GET", "/ut/v1/radio", query={"seed": ids["Lighthouse Keeper"]})
    assert response.status_code == 404, response.text


def test_an_import_by_url_and_its_progress() -> None:
    created = ut(
        "POST", "/ut/v1/imports", body={"url": YT_PLAYLIST_URL}, media_type="application/json"
    )
    assert created.status_code in {201, 202}, created.text
    import_id = created.json()["id"]
    ut("GET", "/ut/v1/imports/{importId}", path_parameters={"importId": import_id})


# ---------------------------------------------------------------- a download job end to end


def internal(method: str, path: str, **parts: Any) -> Any:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    return call(INTERNAL, method, path, headers=headers, **parts)


@pytest.fixture
def claimed() -> Iterator[dict[str, Any]]:
    """An external song kept by the user (a pending track and its download job, as a star or a
    stream would), claimed by a contract worker; failed for good afterwards."""
    anyio.run(keep, SERVICES, USER_ID, [YT_OTHER])
    claim = internal(
        "POST",
        "/internal/v1/jobs/claim",
        body={"workerId": "contract-worker", "kinds": ["download"], "leaseSeconds": 60},
    )
    assert claim.status_code == 200, claim.text
    job: dict[str, Any] = claim.json()
    yield job
    fail = {
        "leaseId": job["lease"]["leaseId"],
        "errorCode": "invalid_video_id",
        "retryable": False,
        "message": "contract test",
    }
    job_id = {"jobId": job["job"]["id"]}
    internal("POST", "/internal/v1/jobs/{jobId}/fail", path_parameters=job_id, body=fail)


def test_a_claimed_job_heartbeats_and_reports_progress(claimed: dict[str, Any]) -> None:
    job_id = {"jobId": claimed["job"]["id"]}
    lease = claimed["lease"]["leaseId"]
    beat = internal(
        "POST",
        "/internal/v1/jobs/{jobId}/heartbeat",
        path_parameters=job_id,
        body={"leaseId": lease, "leaseSeconds": 60},
    )
    assert beat.status_code == 200, beat.text
    staging = claimed["job"]["stagingDir"]
    video = claimed["job"]["videoId"]
    progress = {
        "leaseId": lease,
        "state": "downloading",
        "progress": 0.1,
        "bytesDownloaded": 100,
        "expectedSize": 1000,
        "partPath": f"{staging}/{video}.webm.part",
        "finalPath": f"{staging}/{video}.webm",
        "finished": False,
        "formatId": "251",
        "contentType": "audio/webm",
        "progressive": True,
    }
    path = "/internal/v1/jobs/{jobId}/progress"
    sent = internal("POST", path, path_parameters=job_id, body=progress)
    assert sent.status_code == 200, sent.text


def test_a_worker_status_with_a_canary_result() -> None:
    body = {
        "version": "0.1.0",
        "ytdlpVersion": "2026.09.28",
        "canary": {"at": "2026-10-12T03:00:12.000Z", "ok": False, "message": "download: bot wall"},
    }
    path = "/internal/v1/workers/{workerId}/status"
    response = internal("PUT", path, path_parameters={"workerId": "w1"}, body=body)
    assert response.status_code == 200, response.text
