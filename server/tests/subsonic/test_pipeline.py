# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The OpenSubsonic pipeline: parameters, format, version, auth and error rendering."""

from collections.abc import AsyncIterator, Iterator, Mapping, Sequence

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import Response, StreamingResponse

from ultimatetunes.core.authn import Principal
from ultimatetunes.core.services import build_services
from ultimatetunes.errors import InvalidApiKey, NotFound
from ultimatetunes.settings import Settings
from ultimatetunes.subsonic.router import (
    MAX_FORM_BYTES,
    SubsonicRequest,
    SubsonicRouter,
    build_rest_router,
)

ANA = Principal("0199d6a2-4c1e-7b3a-9f10-2a6c8e01e001", "ana", "user")


class KeyAuthenticator:
    def authenticate_subsonic(
        self, params: Mapping[str, Sequence[str]], client_ip: str | None
    ) -> Principal:
        if params.get("apiKey") != ["utk_good"]:
            raise InvalidApiKey()
        return ANA

    def authenticate_api_key(
        self, header_key: str | None, query_key: str | None, client_ip: str | None
    ) -> Principal:
        raise NotImplementedError


router = SubsonicRouter()


@router.endpoint("echo")
def echo(req: SubsonicRequest) -> Mapping[str, object]:
    return {
        "echo": {
            "user": req.user.username,
            "id": req.require("id"),
            "ids": req.get_all("id"),
            "count": req.get_int("count", 5),
            "missing": req.get("nope"),
        }
    }


@router.endpoint("open", public=True)
async def open_endpoint(req: SubsonicRequest) -> Mapping[str, object]:
    with pytest.raises(RuntimeError):
        _ = req.user
    return {"open": {"ok": True}}


@router.endpoint("raw", head=True)
async def raw(req: SubsonicRequest) -> Response:
    return Response(b"bytes", media_type="audio/ogg")


BODIES_STARTED: list[str] = []


@router.endpoint("growing", head=True)
async def growing(req: SubsonicRequest) -> Response:
    async def body() -> AsyncIterator[bytes]:
        BODIES_STARTED.append(req.request.method)
        yield b"audio"

    return StreamingResponse(body(), media_type="audio/webm", headers={"Accept-Ranges": "none"})


@router.endpoint("missing")
def missing(req: SubsonicRequest) -> Mapping[str, object]:
    raise NotFound("Song not found")


@router.endpoint("crash")
def crash(req: SubsonicRequest) -> Mapping[str, object]:
    raise RuntimeError("secret detail apiKey=utk_x")


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    services = build_services(settings)
    services.authenticator = KeyAuthenticator()
    app = FastAPI()
    app.state.services = services
    app.include_router(build_rest_router([router]))
    with TestClient(app) as test_client:
        yield test_client
    services.db.close()


def ok_body(response: object) -> dict[str, object]:
    assert hasattr(response, "json")
    data: dict[str, dict[str, object]] = response.json()
    return data["subsonic-response"]


def test_get_with_query_parameters_json(client: TestClient) -> None:
    r = client.get("/rest/echo", params={"apiKey": "utk_good", "f": "json", "id": ["a", "b"]})
    body = ok_body(r)
    assert body["status"] == "ok"
    assert body["echo"] == {
        "user": "ana",
        "id": "a",
        "ids": ["a", "b"],
        "count": 5,
        "missing": None,
    }


def test_form_post_and_view_suffix_xml(client: TestClient) -> None:
    r = client.post(
        "/rest/echo.view",
        content="apiKey=utk_good&id=x&count=3",
        headers={"content-type": "application/x-www-form-urlencoded; charset=utf-8"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/xml")
    assert '<echo user="ana" id="x" count="3">' in r.text


def test_errors_use_the_requested_format(client: TestClient) -> None:
    r = client.get("/rest/echo", params={"apiKey": "bad", "f": "json"})
    assert r.status_code == 200
    assert ok_body(r)["error"] == {"code": 44, "message": "Invalid API key"}
    r = client.get("/rest/missing", params={"apiKey": "utk_good"})
    assert 'code="70"' in r.text
    r = client.get("/rest/echo", params={"apiKey": "utk_good", "f": "json"})
    assert ok_body(r)["error"] == {"code": 10, "message": "Required parameter is missing: id"}
    r = client.get(
        "/rest/echo", params={"apiKey": "utk_good", "f": "json", "id": "a", "count": "x"}
    )
    assert ok_body(r)["error"] == {"code": 0, "message": "Parameter count must be an integer"}


def test_unsupported_format_and_newer_protocol(client: TestClient) -> None:
    r = client.get("/rest/open", params={"f": "jsonp"})
    assert 'code="0"' in r.text
    r = client.get("/rest/open", params={"f": "json", "v": "2.0.0"})
    assert ok_body(r)["error"] == {
        "code": 30,
        "message": "Incompatible protocol version: the server must upgrade",
    }
    assert ok_body(client.get("/rest/open", params={"f": "json", "v": "1.16.1"}))["open"] == {
        "ok": True
    }


def test_binary_responses_pass_through(client: TestClient) -> None:
    r = client.get("/rest/raw", params={"apiKey": "utk_good"})
    assert r.content == b"bytes"


def test_unexpected_errors_are_internal_without_details(client: TestClient) -> None:
    r = client.get("/rest/crash", params={"apiKey": "utk_good", "f": "json"})
    error = ok_body(r)["error"]
    assert isinstance(error, dict)
    assert error["code"] == 0
    assert "secret" not in str(error["message"])


def test_oversized_form_is_refused(client: TestClient) -> None:
    r = client.post(
        "/rest/open",
        content="x=" + "a" * MAX_FORM_BYTES,
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert 'message="Form body too large"' in r.text


def test_duplicate_endpoints_are_refused() -> None:
    other = SubsonicRouter()
    other.endpoint("echo")(echo)
    with pytest.raises(ValueError, match="twice"):
        other.endpoint("echo")(echo)
    with pytest.raises(ValueError, match="twice"):
        build_rest_router([router, router])


def test_head_on_binary_endpoints_has_headers_and_no_body(client: TestClient) -> None:
    r = client.head("/rest/raw", params={"apiKey": "utk_good"})
    assert r.status_code == 200
    assert r.content == b""
    assert r.headers["content-length"] == "5"
    assert r.headers["content-type"] == "audio/ogg"
    r = client.head("/rest/growing.view", params={"apiKey": "utk_good"})
    assert r.status_code == 200
    assert r.headers["accept-ranges"] == "none"
    assert "content-length" not in r.headers
    assert BODIES_STARTED == []
    assert client.get("/rest/growing", params={"apiKey": "utk_good"}).content == b"audio"
    assert BODIES_STARTED == ["GET"]
    r = client.head("/rest/raw", params={"apiKey": "bad"})
    assert r.status_code == 200
    assert r.content == b""


def test_head_is_refused_on_other_endpoints(client: TestClient) -> None:
    assert client.head("/rest/open").status_code == 405


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_unknown_endpoints_answer_error_0_in_the_requested_format(
    client: TestClient, method: str
) -> None:
    r = client.request(method, "/rest/getNowPlaying", params={"f": "json"})
    assert r.status_code == 200
    assert ok_body(r)["error"] == {"code": 0, "message": "Unknown endpoint: getNowPlaying"}
    r = client.request(method, "/rest/a/b.view")
    assert r.status_code == 200
    assert '<error code="0" message="Unknown endpoint: a/b.view"/>' in r.text
    r = client.request(method, "/rest/x", params={"f": "yaml"})
    assert '<error code="0"' in r.text
