# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The access log: the resolved client address, no credentials, 429 as `ratelimit.hit`."""

import json
import logging
import secrets
from collections.abc import Iterator

import pytest
from starlette.types import Message, Receive, Scope, Send

from tests.security_events import collect, rendered
from ultimatetunes.core.accesslog import LOGGER_NAME, AccessLog
from ultimatetunes.core.netaddr import parse_networks

PROXY = parse_networks("10.213.46.1/32")
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def ticking() -> Iterator[float]:
    yield 10.0
    yield 10.25


def responder(status: int, body: bytes = b"hello") -> object:
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": body, "more_body": True})
        await send({"type": "http.response.body", "body": b""})

    return app


def http(path: str, peer: str, headers: dict[str, str] | None = None, query: str = "") -> Scope:
    return {
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": query.encode(),
        "client": (peer, 40000),
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
    }


async def receive() -> Message:
    return {"type": "http.request"}


async def discard(_message: Message) -> None:
    return None


async def run(app: object, scope: Scope, listener: str = "client") -> None:
    clock = ticking()
    log = AccessLog(app, proxies=PROXY, listener=listener, timer=lambda: next(clock))  # type: ignore[arg-type]
    await log(scope, receive, discard)


@pytest.fixture
def capture(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.INFO)
    return caplog


async def test_behind_the_trusted_proxy_the_client_is_resolved(
    capture: pytest.LogCaptureFixture,
) -> None:
    headers = {"X-Forwarded-For": "100.64.7.8", "User-Agent": "Feishin/1.0"}
    await run(responder(200), http("/rest/ping.view", "10.213.46.1", headers))
    (line,) = collect(capture, "http.request")
    assert line == {
        "event": "http.request",
        "client_ip": "100.64.7.8",
        "peer_ip": "10.213.46.1",
        "method": "GET",
        "path": "/rest/ping.view",
        "status": 200,
        "bytes": 5,
        "duration_ms": 250.0,
        "surface": "subsonic",
        "listener": "client",
        "user_agent": "Feishin/1.0",
    }
    assert capture.records[0].name == LOGGER_NAME
    assert capture.records[0].getMessage() == '100.64.7.8 "GET /rest/ping.view" 200'


async def test_forwarding_headers_from_an_untrusted_peer_are_flagged(
    capture: pytest.LogCaptureFixture,
) -> None:
    await run(responder(403), http("/admin", "198.51.100.3", {"X-Forwarded-For": "192.168.1.2"}))
    (line,) = collect(capture, "http.request")
    assert line["client_ip"] == "198.51.100.3"  # never the forged address
    assert line["via_untrusted_proxy"] is True
    assert "user_agent" not in line


async def test_credentials_in_the_query_never_reach_the_log(
    capture: pytest.LogCaptureFixture,
) -> None:
    secret = secrets.token_urlsafe(24)
    query = f"u=ana&p={secret}&apiKey={secret}&t={secret}&s={secret}&id=42&f=json"
    await run(responder(200), http("/rest/stream.view", "192.0.2.5", query=query))
    out = rendered(capture)
    assert secret not in out
    entry = json.loads(out)
    assert "id=42" in entry["query"]
    assert "[REDACTED]" in entry["query"]


async def test_a_429_is_also_a_rate_limit_event(capture: pytest.LogCaptureFixture) -> None:
    await run(responder(429), http("/web/login", "203.0.113.50"))
    (hit,) = collect(capture, "ratelimit.hit")
    assert hit == {
        "event": "ratelimit.hit",
        "client_ip": "203.0.113.50",
        "method": "GET",
        "path": "/web/login",
        "surface": "web",
        "listener": "client",
    }
    assert any(r.levelno == logging.WARNING for r in capture.records)


async def test_refusals_of_the_listener_itself_are_logged(
    capture: pytest.LogCaptureFixture,
) -> None:
    """`/internal/*` on the client port never reaches the app: the access log still sees it."""
    await run(responder(404, b"Not Found"), http("/internal/v1/jobs/claim", "192.0.2.9"))
    (line,) = collect(capture, "http.request")
    assert (line["status"], line["surface"]) == (404, "internal")


async def test_an_unhandled_error_is_logged_as_500_and_raised(
    capture: pytest.LogCaptureFixture,
) -> None:
    async def broken(scope: Scope, receive: Receive, send: Send) -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await run(broken, http("/ut/v1/me", "192.0.2.9"))
    (line,) = collect(capture, "http.request")
    assert (line["status"], line["bytes"]) == (500, 0)


async def test_an_error_after_the_headers_keeps_their_status(
    capture: pytest.LogCaptureFixture,
) -> None:
    async def cut(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 206, "headers": []})
        raise RuntimeError("client went away")

    with pytest.raises(RuntimeError):
        await run(cut, http("/rest/stream", "192.0.2.9"))
    assert collect(capture, "http.request")[0]["status"] == 206


async def test_other_scopes_pass_through(capture: pytest.LogCaptureFixture) -> None:
    seen: list[str] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["type"])

    await run(app, {"type": "lifespan"})
    assert seen == ["lifespan"]
    assert collect(capture) == []


async def test_without_a_peer_the_client_is_unknown(capture: pytest.LogCaptureFixture) -> None:
    scope = http("/healthz", "192.0.2.1")
    scope["client"] = None
    await run(responder(200, b"ok"), scope, listener="internal")
    (line,) = collect(capture, "http.request")
    assert "client_ip" not in line
    assert "peer_ip" not in line
    assert line["listener"] == "internal"


async def test_other_messages_are_passed_on_and_not_counted(
    capture: pytest.LogCaptureFixture,
) -> None:
    sent: list[str] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": [], "trailers": True})
        await send({"type": "http.response.body", "body": b"abc"})
        await send({"type": "http.response.trailers", "headers": [], "more_trailers": False})

    async def record(message: Message) -> None:
        sent.append(message["type"])

    log = AccessLog(app, proxies=PROXY, listener="client")
    await log(http("/rest/stream", "192.0.2.9"), receive, record)
    assert sent[-1] == "http.response.trailers"
    assert collect(capture, "http.request")[0]["bytes"] == 3
