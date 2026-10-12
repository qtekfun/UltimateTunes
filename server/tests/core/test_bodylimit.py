# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The api-wide request body cap (core/bodylimit.py, T22)."""

import logging
from collections.abc import Iterator

import pytest
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from ultimatetunes.app import create_app
from ultimatetunes.core.bodylimit import BodyLimit
from ultimatetunes.settings import Settings


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def echo(scope: Scope, receive: Receive, send: Send) -> None:
    if scope["type"] != "http":  # pragma: no cover - TestClient without `with`
        return
    body = await Request(scope, receive).body()
    await PlainTextResponse(f"{len(body)}")(scope, receive, send)


def chunks(total: int, size: int = 1000) -> Iterator[bytes]:
    yield from (b"x" * size for _ in range(total // size))


def test_declared_bodies_over_the_cap_are_refused_before_the_app() -> None:
    client = TestClient(BodyLimit(echo, 5000))
    assert client.post("/", content=b"x" * 5000).text == "5000"
    r = client.post("/", content=b"x" * 5001)
    assert r.status_code == 413
    assert r.json()["type"].endswith("payload_too_large")
    r = client.post("/", content=b"x", headers={"content-length": "nope"})
    assert r.status_code == 413


def test_chunked_bodies_over_the_cap_get_413_without_reaching_the_app(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = TestClient(BodyLimit(echo, 5000))
    assert client.post("/", content=chunks(5000)).text == "5000"
    with caplog.at_level(logging.DEBUG):
        r = client.post("/", content=chunks(9000))
    assert r.status_code == 413
    assert r.json()["type"].endswith("payload_too_large")
    assert not [rec for rec in caplog.records if rec.levelno >= logging.ERROR]


@pytest.mark.anyio
async def test_a_client_that_leaves_before_its_body_is_dropped() -> None:
    called: list[Scope] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:  # pragma: no cover
        called.append(scope)

    async def receive() -> Message:
        return {"type": "http.disconnect"}

    async def send(_message: Message) -> None:  # pragma: no cover - nothing is sent
        raise AssertionError("sent a response to a gone client")

    await BodyLimit(app, 10)({"type": "http", "path": "/", "headers": []}, receive, send)
    assert called == []


@pytest.mark.anyio
async def test_after_the_replayed_body_reads_go_to_the_server() -> None:
    incoming: list[Message] = [
        {"type": "http.request", "body": b"ab", "more_body": True},
        {"type": "http.request", "body": b"c", "more_body": False},
        {"type": "http.disconnect"},
    ]
    seen: list[Message] = []

    async def receive() -> Message:
        return incoming.pop(0)

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(await receive())
        seen.append(await receive())

    async def send(_message: Message) -> None:  # pragma: no cover - the app sends nothing
        return

    await BodyLimit(app, 10)({"type": "http", "path": "/", "headers": []}, receive, send)
    assert seen == [
        {"type": "http.request", "body": b"abc", "more_body": False},
        {"type": "http.disconnect"},
    ]


def test_the_app_applies_the_cap(settings: Settings) -> None:
    small = settings.model_copy(update={"max_body_bytes": 64 * 1024})
    client = TestClient(create_app(small), client=("127.0.0.1", 1))
    r = client.post("/rest/ping.view", content=b"x" * (64 * 1024 + 1))
    assert r.status_code == 413
    # Every answer says nosniff, the APIs' too.
    assert client.get("/rest/ping.view").headers["x-content-type-options"] == "nosniff"
    assert client.get("/healthz").headers["x-content-type-options"] == "nosniff"
