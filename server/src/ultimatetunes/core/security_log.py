# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Structured security events for log analysis (docs/logging.md, SECURITY.md).

`security_event` writes one JSON line on the `ultimatetunes.security` logger with a stable
`event` name (`auth.failure`, `auth.lockout`, ...) and flat fields (`client_ip`, `user`,
`reason`, `surface`, ...), so a SIEM or CrowdSec can match them without parsing free text. The
line goes through the same redacting JSON handler as every other log line (`logging.py`), and
callers never pass a password, a key, a token or a cookie: only names, ids and reasons.

`RequestContext` is an ASGI middleware placed right inside `core.forwarded.ClientAddress`: it
records the resolved client address, the method, the path (never the query string) and the
surface of the current request in a `ContextVar`, so an event raised deep inside a handler
(or in `run_in_threadpool`, which copies the context) carries them without passing the request
around. Explicit fields win over the request's.
"""

import logging
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass

from starlette.types import ASGIApp, Receive, Scope, Send

from ultimatetunes.logging import FIELDS_ATTR

LOGGER_NAME = "ultimatetunes.security"
# Attacker-controlled strings (usernames, paths, user agents) are cut to this length.
MAX_FIELD_CHARS = 256

FieldValue = str | int | float | bool | None

log = logging.getLogger(LOGGER_NAME)


@dataclass(frozen=True)
class RequestInfo:
    client_ip: str | None
    method: str
    path: str
    surface: str


_REQUEST: ContextVar[RequestInfo | None] = ContextVar("ut_security_request", default=None)

# (prefix, surface), first match wins; `exact` entries match the whole path only.
_EXACT = {"/ut/v1/keys": "ut_keys", "/": "web", "/healthz": "probe", "/readyz": "probe"}
_PREFIXES = (
    ("/admin", "admin"),
    ("/web", "web"),
    ("/rest", "subsonic"),
    ("/ut/v1", "ut"),
    ("/internal", "internal"),
)


def surface_of(path: str) -> str:
    """Which part of the api a path belongs to (the `surface` field of every event)."""
    if path in _EXACT:
        return _EXACT[path]
    for prefix, surface in _PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return surface
    return "other"


def current_request() -> RequestInfo | None:
    return _REQUEST.get()


def clip(value: FieldValue) -> FieldValue:
    if isinstance(value, str) and len(value) > MAX_FIELD_CHARS:
        return value[:MAX_FIELD_CHARS] + "..."
    return value


def security_event(
    event: str,
    *,
    level: int = logging.INFO,
    message: str | None = None,
    **fields: FieldValue,
) -> None:
    """Logs one security event (module doc). Fields that are None are left out; `message` is
    the human-readable text (default: the event name and its reason)."""
    emit(event, fields, level=level, message=message)


def emit(
    event: str,
    fields: Mapping[str, FieldValue],
    *,
    level: int = logging.INFO,
    message: str | None = None,
) -> None:
    """`security_event` with the fields as a mapping."""
    merged: dict[str, FieldValue] = {}
    info = _REQUEST.get()
    if info is not None:
        merged.update(
            client_ip=info.client_ip, surface=info.surface, method=info.method, path=info.path
        )
    merged.update(fields)
    clean = {name: clip(value) for name, value in merged.items() if value is not None}
    reason = clean.get("reason")
    text = message or (f"{event} ({reason})" if reason is not None else event)
    log.log(level, "%s", text, extra={FIELDS_ATTR: {"event": event, **clean}})


class RequestContext:
    """Plain ASGI middleware: the current request's `RequestInfo` (module doc)."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        client = scope.get("client")
        path: str = scope.get("path", "")
        info = RequestInfo(
            client[0] if client else None, scope.get("method", ""), path, surface_of(path)
        )
        token = _REQUEST.set(info)
        try:
            await self._app(scope, receive, send)
        finally:
            _REQUEST.reset(token)
