# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A cap on request bodies for the whole api (`UT_MAX_BODY_BYTES`, 4 MiB; SECURITY.md, T22).

The largest legitimate body is a playlist import file (1 MiB, `imports/upload.py`); areas keep
their own tighter caps (the admin panel 64 KiB). This one holds when no proxy limits bodies
(`tailscale serve` does not): a declared length above the cap gets 413 (`payload_too_large`)
before the app runs, and a chunked body is cut off at the cap (the app sees the client
disconnect).

`NoSniff` adds `X-Content-Type-Options: nosniff` to every answer (the admin panel already sets
its own, stricter set of headers).
"""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ultimatetunes.errors import PayloadTooLarge
from ultimatetunes.problem import problem_response


class BodyLimit:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self._app = app
        self._max = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        declared = _content_length(scope)
        if declared is not None and declared > self._max:
            refusal = problem_response(
                PayloadTooLarge("The request body is too large"), scope["path"]
            )
            await refusal(scope, receive, send)
            return
        received = 0

        async def limited() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._max:
                    return {"type": "http.disconnect"}
            return message

        await self._app(scope, limited, send)


def _content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name.lower() == b"content-length":
            try:
                return int(value)
            except ValueError:
                return 1 << 62  # unreadable: refused like an oversized body
    return None


class NoSniff:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).setdefault("X-Content-Type-Options", "nosniff")
            await send(message)

        await self._app(scope, receive, with_header)
