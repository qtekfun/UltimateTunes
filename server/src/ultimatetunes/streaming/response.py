# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`TailResponse`: the body of a growing file, and what ends it.

- The body is an async iterator (`service.tail`) that raises `StreamAborted` when the transfer
  must be cut. The response then raises it again **after** the last chunk it sent, so the server
  closes the connection without a clean end: before `Content-Length` bytes, or without the
  final zero-length chunk (contracts/errors.md, T03a: never pass a broken file off as
  complete).
- A client that goes away is noticed at once, even while the body waits for the next report
  (the body is cancelled), so its listener slot is freed without waiting for more bytes.
- `release` runs exactly once whatever happens (the listener slots, the watcher, the cleanup),
  even when the body never starts.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping

import anyio
from starlette.responses import Response
from starlette.types import Receive, Scope, Send


class StreamAborted(Exception):  # noqa: N818 - the transfer is aborted on purpose
    """The transfer must end without a clean end."""


class TailResponse(Response):
    def __init__(
        self,
        body: AsyncIterator[bytes],
        *,
        status_code: int,
        headers: Mapping[str, str],
        release: Callable[[], Awaitable[None]],
    ) -> None:
        self.body_iterator = body
        self.status_code = status_code
        self.background = None
        self._release = release
        self.init_headers(headers)

    async def _send_body(self, send: Send) -> None:
        await send(
            {"type": "http.response.start", "status": self.status_code, "headers": self.raw_headers}
        )
        async for chunk in self.body_iterator:
            await send({"type": "http.response.body", "body": chunk, "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        aborted: StreamAborted | None = None
        try:
            async with anyio.create_task_group() as group:

                async def disconnect() -> None:
                    while (await receive())["type"] != "http.disconnect":
                        pass
                    group.cancel_scope.cancel()

                group.start_soon(disconnect)
                try:
                    await self._send_body(send)
                except StreamAborted as exc:
                    aborted = exc
                group.cancel_scope.cancel()
        finally:
            with anyio.CancelScope(shield=True):
                await self._release()
        if aborted is not None:
            raise aborted
