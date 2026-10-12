# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""LRCLIB client against respx fixtures (no network)."""

import httpx
import pytest
import respx

from tests.lyrics.helpers import fixture_bytes as fixture
from ultimatetunes.lyrics.lrclib import (
    DEFAULT_RETRY_AFTER_S,
    MAX_BODY_BYTES,
    USER_AGENT,
    LrclibClient,
    LrclibQuery,
    LrclibRecord,
    LrclibThrottled,
    LrclibUnavailable,
    retry_after,
)

QUERY = LrclibQuery("Lighthouse Keeper", "The Paper Lanterns", "Harbour Lights", 212)


def test_found_record_and_request_etiquette(lrclib: respx.MockRouter) -> None:
    route = lrclib.get("/api/get").respond(
        200, content=fixture("lighthouse_keeper.json"), content_type="application/json"
    )
    record = LrclibClient().get(QUERY)
    assert record is not None
    assert record.id == 4242001
    assert not record.instrumental
    assert record.synced_lyrics is not None
    assert record.synced_lyrics.startswith("[00:00.00] Salt")
    assert record.plain_lyrics is not None
    request = route.calls.last.request
    assert request.url.host == "lrclib.net"
    assert request.url.scheme == "https"
    assert request.headers["user-agent"] == USER_AGENT
    assert "github.com/qtekfun/UltimateTunes" in USER_AGENT
    assert USER_AGENT.startswith("UltimateTunes/")
    assert dict(request.url.params) == {
        "track_name": "Lighthouse Keeper",
        "artist_name": "The Paper Lanterns",
        "album_name": "Harbour Lights",
        "duration": "212",
    }


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (LrclibQuery("T", "A"), {"track_name": "T", "artist_name": "A"}),
        (LrclibQuery("T", "A", "", 0), {"track_name": "T", "artist_name": "A"}),
        (LrclibQuery("T", "A", None, 3601), {"track_name": "T", "artist_name": "A"}),
        (LrclibQuery("T", "A", None, 1), {"track_name": "T", "artist_name": "A", "duration": "1"}),
        (
            LrclibQuery("T", "A", None, 3600),
            {"track_name": "T", "artist_name": "A", "duration": "3600"},
        ),
    ],
)
def test_query_parameters(query: LrclibQuery, expected: dict[str, str]) -> None:
    assert query.params() == expected


def test_instrumental_record(lrclib: respx.MockRouter) -> None:
    lrclib.get("/api/get").respond(200, content=fixture("instrumental.json"))
    assert LrclibClient().get(QUERY) == LrclibRecord(4242003, True, None, None)


def test_empty_strings_are_no_lyrics(lrclib: respx.MockRouter) -> None:
    lrclib.get("/api/get").respond(200, json={"id": 7, "plainLyrics": "", "syncedLyrics": ""})
    assert LrclibClient().get(QUERY) == LrclibRecord(7, False, None, None)


@pytest.mark.parametrize("status", [404, 400])
def test_not_found_and_unmatchable_query(lrclib: respx.MockRouter, status: int) -> None:
    lrclib.get("/api/get").respond(status, content=fixture("not_found.json"))
    assert LrclibClient().get(QUERY) is None


@pytest.mark.parametrize("status", [429, 503])
def test_throttling_carries_retry_after(lrclib: respx.MockRouter, status: int) -> None:
    lrclib.get("/api/get").respond(status, headers={"Retry-After": "17"}, text="slow down")
    with pytest.raises(LrclibThrottled) as caught:
        LrclibClient().get(QUERY)
    assert caught.value.retry_after_s == 17


@pytest.mark.parametrize(
    ("header", "seconds"),
    [
        (None, DEFAULT_RETRY_AFTER_S),
        ("soon", DEFAULT_RETRY_AFTER_S),
        ("Wed, 21 Oct 2026 07:28:00 GMT", DEFAULT_RETRY_AFTER_S),
        ("0", 1),
        (" 5 ", 5),
        ("999999", 3600),
    ],
)
def test_retry_after_parsing(header: str | None, seconds: int) -> None:
    headers = {} if header is None else {"Retry-After": header}
    assert retry_after(httpx.Response(429, headers=headers)) == seconds


@pytest.mark.parametrize("status", [500, 502, 301, 302, 403])
def test_other_statuses_are_unavailable(lrclib: respx.MockRouter, status: int) -> None:
    lrclib.get("/api/get").respond(status, headers={"Location": "https://example.org/"})
    with pytest.raises(LrclibUnavailable):
        LrclibClient().get(QUERY)


def test_redirects_are_not_followed(lrclib: respx.MockRouter) -> None:
    lrclib.get("/api/get").respond(302, headers={"Location": "https://example.org/x"})
    other = lrclib.get("https://example.org/x").respond(200, json={"id": 1})
    with pytest.raises(LrclibUnavailable):
        LrclibClient().get(QUERY)
    assert not other.called


@pytest.mark.parametrize(
    "error", [httpx.ConnectTimeout("t"), httpx.ReadTimeout("t"), httpx.ConnectError("c")]
)
def test_transport_errors_are_unavailable(lrclib: respx.MockRouter, error: Exception) -> None:
    lrclib.get("/api/get").mock(side_effect=error)
    with pytest.raises(LrclibUnavailable):
        LrclibClient().get(QUERY)


@pytest.mark.parametrize(
    "body",
    [
        b"<html>gateway</html>",
        b"\xff\xfe\x00broken",
        b"[1, 2]",
        b'{"plainLyrics": "x"}',
        b'{"id": "12"}',
        b'{"id": true}',
        b'{"id": 1, "syncedLyrics": 5}',
        b'{"id": 1, "plainLyrics": ["x"]}',
    ],
)
def test_unreadable_bodies_are_unavailable(lrclib: respx.MockRouter, body: bytes) -> None:
    lrclib.get("/api/get").respond(200, content=body)
    with pytest.raises(LrclibUnavailable):
        LrclibClient().get(QUERY)


def test_oversized_body_is_unavailable(lrclib: respx.MockRouter) -> None:
    lrclib.get("/api/get").respond(200, content=b" " * (MAX_BODY_BYTES + 1))
    with pytest.raises(LrclibUnavailable, match="too large"):
        LrclibClient().get(QUERY)


def test_custom_transport_is_used() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(404)

    client = LrclibClient(timeout_s=1.0, transport=httpx.MockTransport(handler))
    assert client.get(QUERY) is None
    assert seen[0].url.path == "/api/get"
