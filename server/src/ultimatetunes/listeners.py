# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The api's two listeners (SECURITY.md, T22).

One app (one set of services, one lifespan, one in-process `JobWatch`) is served on two ports:

- the **client listener** (`UT_PORT`, 8044): everything except the internal worker API, which
  answers 404 there as if it did not exist;
- the **internal listener** (`UT_INTERNAL_PORT`, 8045): only `/internal/v1` and `/healthz`.

Compose publishes only the client port; the internal one stays on the internal Docker network,
where the worker reaches it (`UT_API_URL=http://api:8045`). Both share the same app object,
so worker reports still wake the streams of the client listener at once.

uvicorn installs its own SIGTERM handler per server; only the client listener does that here
and the internal listener follows it (`Follower`), so one signal stops both gracefully.
"""

import asyncio
import contextlib
from collections.abc import Iterator

import uvicorn
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

INTERNAL_PREFIX = "/internal/"
# Paths both listeners answer.
SHARED_PATHS = frozenset({"/healthz"})


def is_internal_path(path: str) -> bool:
    return path == INTERNAL_PREFIX.rstrip("/") or path.startswith(INTERNAL_PREFIX)


class Listener:
    """The app as one listener sees it: requests for the other listener get a plain 404."""

    def __init__(self, app: ASGIApp, *, internal: bool) -> None:
        self.app = app
        self.internal = internal

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            path: str = scope["path"]
            if path not in SHARED_PATHS and is_internal_path(path) != self.internal:
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                    return
                await PlainTextResponse("Not Found", status_code=404)(scope, receive, send)
                return
        await self.app(scope, receive, send)


class Follower(uvicorn.Server):
    """A server that installs no signal handlers and stops when its leader stops."""

    def __init__(self, config: uvicorn.Config, leader: uvicorn.Server) -> None:
        super().__init__(config)
        self.leader = leader

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield

    async def on_tick(self, counter: int) -> bool:
        if self.leader.should_exit:
            self.should_exit = True
        return await super().on_tick(counter)


async def serve(client: uvicorn.Config, internal: uvicorn.Config) -> None:
    """Serves both listeners until a signal stops the client one (and with it the other)."""
    leader = uvicorn.Server(client)
    await asyncio.gather(leader.serve(), Follower(internal, leader).serve())
