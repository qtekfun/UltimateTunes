# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A cap on request bodies for the whole api (`UT_MAX_BODY_BYTES`, 4 MiB; SECURITY.md, T22).

The largest legitimate body is a playlist import file (1 MiB, `imports/upload.py`); areas keep
their own tighter caps (the admin panel 64 KiB). This one holds when no proxy limits bodies
(`tailscale serve` does not): a declared length above the cap gets 413 (`payload_too_large`)
before the app runs; a body without a declared length (chunked) is read here up to the cap
and answered 413 the same way past it, otherwise handed to the app whole.

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
        if declared is not None:
            if declared > self._max:
                await _too_large(scope, receive, send)
                return
            # The server enforces the declared length, so the body cannot grow past it.
            await self._app(scope, receive, send)
            return
        # No declared length (chunked): read it here, up to the cap, before the app runs.
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return  # the client went away before sending its body
            chunk: bytes = message.get("body", b"")
            size += len(chunk)
            if size > self._max:
                await _too_large(scope, receive, send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self._app(scope, replay, send)


async def _too_large(scope: Scope, receive: Receive, send: Send) -> None:
    refusal = problem_response(PayloadTooLarge("The request body is too large"), scope["path"])
    await refusal(scope, receive, send)


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
