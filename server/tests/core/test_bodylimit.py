# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The api-wide request body cap (core/bodylimit.py, T22)."""

from collections.abc import Iterator

from starlette.requests import ClientDisconnect, Request
from starlette.responses import PlainTextResponse
from starlette.testclient import TestClient
from starlette.types import Receive, Scope, Send

from ultimatetunes.app import create_app
from ultimatetunes.core.bodylimit import BodyLimit
from ultimatetunes.settings import Settings


async def echo(scope: Scope, receive: Receive, send: Send) -> None:
    if scope["type"] != "http":  # pragma: no cover - TestClient without `with`
        return
    try:
        body = await Request(scope, receive).body()
    except ClientDisconnect:
        await PlainTextResponse("cut", status_code=400)(scope, receive, send)
        return
    await PlainTextResponse(f"{len(body)}")(scope, receive, send)


def chunks(total: int, size: int = 1000) -> Iterator[bytes]:
    for _ in range(total // size):
        yield b"x" * size


def test_declared_bodies_over_the_cap_are_refused_before_the_app() -> None:
    client = TestClient(BodyLimit(echo, 5000))
    assert client.post("/", content=b"x" * 5000).text == "5000"
    r = client.post("/", content=b"x" * 5001)
    assert r.status_code == 413
    assert r.json()["type"].endswith("payload_too_large")
    r = client.post("/", content=b"x", headers={"content-length": "nope"})
    assert r.status_code == 413


def test_chunked_bodies_are_cut_at_the_cap() -> None:
    client = TestClient(BodyLimit(echo, 5000))
    assert client.post("/", content=chunks(5000)).text == "5000"
    assert client.post("/", content=chunks(9000)).status_code == 400


def test_the_app_applies_the_cap(settings: Settings) -> None:
    small = settings.model_copy(update={"max_body_bytes": 64 * 1024})
    client = TestClient(create_app(small), client=("127.0.0.1", 1))
    r = client.post("/rest/ping.view", content=b"x" * (64 * 1024 + 1))
    assert r.status_code == 413
    # Every answer says nosniff, the APIs' too.
    assert client.get("/rest/ping.view").headers["x-content-type-options"] == "nosniff"
    assert client.get("/healthz").headers["x-content-type-options"] == "nosniff"
