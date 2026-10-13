# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Structured security events: fields, request context, JSON output and redaction."""

import json
import logging
import secrets

import pytest
from starlette.types import Message, Receive, Scope, Send

from tests.security_events import Events, rendered
from ultimatetunes.core.security_log import (
    LOGGER_NAME,
    MAX_FIELD_CHARS,
    RequestContext,
    clip,
    current_request,
    security_event,
    surface_of,
)
from ultimatetunes.logging import FIELDS_ATTR, JsonFormatter

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize(
    ("path", "surface"),
    [
        ("/", "web"),
        ("/web", "web"),
        ("/web/login", "web"),
        ("/webby", "other"),
        ("/admin", "admin"),
        ("/admin/login", "admin"),
        ("/administrator", "other"),
        ("/rest/ping.view", "subsonic"),
        ("/ut/v1/keys", "ut_keys"),
        ("/ut/v1/keys/abc", "ut"),
        ("/ut/v1/me", "ut"),
        ("/internal/v1/jobs/claim", "internal"),
        ("/healthz", "probe"),
        ("/readyz", "probe"),
        ("/wp-login.php", "other"),
    ],
)
def test_surface_of(path: str, surface: str) -> None:
    assert surface_of(path) == surface


def test_clip_cuts_long_strings_only() -> None:
    long = "a" * (MAX_FIELD_CHARS + 10)
    assert clip(long) == "a" * MAX_FIELD_CHARS + "..."
    assert clip("short") == "short"
    assert clip(5) == 5
    assert clip(None) is None


def test_an_event_has_a_stable_name_and_flat_fields(events: Events) -> None:
    security_event("auth.failure", level=logging.WARNING, reason="bad_password", user="ana")
    security_event("audit", message="audit user.create", action="user.create", user_id=None)
    first, second = events()
    assert first == {"event": "auth.failure", "reason": "bad_password", "user": "ana"}
    assert second == {"event": "audit", "action": "user.create"}  # None fields are left out


def test_message_defaults_to_the_event_and_its_reason(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, LOGGER_NAME)
    security_event("auth.failure", reason="invalid_key")
    security_event("audit", message="audit key.create")
    security_event("csrf.failure")
    assert [r.getMessage() for r in caplog.records] == [
        "auth.failure (invalid_key)",
        "audit key.create",
        "csrf.failure",
    ]
    assert {r.name for r in caplog.records} == {LOGGER_NAME}


def test_the_json_line_has_the_fields_at_the_top_level() -> None:
    record = logging.LogRecord(LOGGER_NAME, logging.WARNING, __file__, 1, "x", None, None)
    fields = {"event": "auth.failure", "client_ip": "198.51.100.4", "message": "forged"}
    setattr(record, FIELDS_ATTR, fields)
    entry = json.loads(JsonFormatter().format(record))
    assert entry["event"] == "auth.failure"
    assert entry["client_ip"] == "198.51.100.4"
    # A field never replaces the four base keys.
    assert (entry["message"], entry["logger"], entry["level"]) == ("x", LOGGER_NAME, "WARNING")


def test_fields_are_redacted_by_name_and_by_value(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    secret = secrets.token_urlsafe(16)
    api_key = "utk_" + secrets.token_urlsafe(32)[:43]
    security_event(
        "auth.failure",
        password=secret,
        token=secret,
        user=f"x apiKey={secret}",
        path=f"/rest/ping?p={secret}",
        note=api_key,
    )
    out = rendered(caplog)
    assert secret not in out
    assert api_key not in out
    entry = json.loads(out)
    assert entry["password"] == entry["token"] == "[REDACTED]"
    assert entry["note"] == "[REDACTED]"


async def test_request_context_gives_events_the_request(events: Events) -> None:
    seen: list[object] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(current_request())
        security_event("csrf.failure", reason="token")
        security_event("audit", client_ip="192.0.2.1")  # explicit fields win

    middleware = RequestContext(app)
    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/admin/users",
        "client": ("100.64.1.2", 40000),
        "query_string": b"",
        "headers": [],
    }

    async def receive() -> Message:
        return {"type": "http.request"}

    async def send(_message: Message) -> None:
        return None

    await middleware(scope, receive, send)
    assert current_request() is None  # reset after the request
    first, second = events()
    assert first == {
        "event": "csrf.failure",
        "reason": "token",
        "client_ip": "100.64.1.2",
        "surface": "admin",
        "method": "POST",
        "path": "/admin/users",
    }
    assert second["client_ip"] == "192.0.2.1"
    await middleware({**scope, "client": None, "path": "/rest/ping"}, receive, send)
    third = events()[2]
    assert "client_ip" not in third
    assert third["surface"] == "subsonic"
    assert len(seen) == 2


async def test_request_context_passes_other_scopes_through() -> None:
    seen: list[object] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append((scope["type"], current_request()))

    async def receive() -> Message:
        return {"type": "lifespan.startup"}

    async def send(_message: Message) -> None:
        return None

    await RequestContext(app)({"type": "lifespan"}, receive, send)
    assert seen == [("lifespan", None)]
