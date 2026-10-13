# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The access log of the api's listeners (docs/logging.md).

uvicorn's own access log shows the TCP peer, which behind `tailscale serve` or a reverse proxy
is always the proxy, and the full query string. `AccessLog` replaces it (`cli.run_api` turns
uvicorn's off): it wraps each listener, outside everything else, so it also sees the requests
the listener refuses on its own (`/internal/*` on the client port), and writes one `http.request`
line per request on the `ultimatetunes.access` logger with the **resolved client address**
(`core.forwarded.resolve`, the same rule and the same `UT_TRUSTED_PROXIES` the app uses), the
TCP peer, method, path, the query string redacted (`logging.redact`: `apiKey`, `p`, `t`, `s`
and every other credential shape), status, response bytes, duration, user agent and surface.

A 429 answer also writes a `ratelimit.hit` security event, whatever limit refused it.
"""

import logging
import time
from collections.abc import Callable

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ultimatetunes.core.forwarded import resolve, via_untrusted_proxy
from ultimatetunes.core.netaddr import IpNetwork
from ultimatetunes.core.security_log import clip, security_event, surface_of
from ultimatetunes.logging import FIELDS_ATTR, redact

LOGGER_NAME = "ultimatetunes.access"
TOO_MANY_REQUESTS = 429
SERVER_ERROR = 500

log = logging.getLogger(LOGGER_NAME)


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return str(value.decode("latin-1"))
    return None


class AccessLog:
    """Plain ASGI middleware around one listener (module doc). `timer` measures durations."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        proxies: tuple[IpNetwork, ...],
        listener: str,
        timer: Callable[[], float] = time.monotonic,
    ) -> None:
        self.app = app
        self.listener = listener
        self.proxies = proxies
        self._timer = timer

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = self._timer()
        status = 0
        sent = 0

        async def counting_send(message: Message) -> None:
            nonlocal status, sent
            if message["type"] == "http.response.start":
                status = int(message["status"])
            elif message["type"] == "http.response.body":
                sent += len(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, counting_send)
        except BaseException:
            status = status or SERVER_ERROR
            raise
        finally:
            self._log(scope, status, sent, self._timer() - started)

    def _log(self, scope: Scope, status: int, sent: int, elapsed_s: float) -> None:
        resolved = resolve(scope, self.proxies)
        client = resolved.get("client")
        peer = scope.get("client")
        client_ip = str(client[0]) if client else None
        method = str(scope.get("method", ""))
        path = str(scope.get("path", ""))
        query = bytes(scope.get("query_string", b"")).decode("latin-1")
        surface = surface_of(path)
        fields = {
            "event": "http.request",
            "client_ip": client_ip,
            "peer_ip": str(peer[0]) if peer else None,
            "method": method,
            "path": clip(path),
            "query": clip(redact(query)) if query else None,
            "status": status,
            "bytes": sent,
            "duration_ms": round(elapsed_s * 1000, 1),
            "surface": surface,
            "listener": self.listener,
            "user_agent": clip(_header(scope, b"user-agent")),
            "via_untrusted_proxy": True if via_untrusted_proxy(resolved) else None,
        }
        log.info(
            '%s "%s %s" %d',
            client_ip,
            method,
            path,
            status,
            extra={FIELDS_ATTR: {k: v for k, v in fields.items() if v is not None}},
        )
        if status == TOO_MANY_REQUESTS:
            security_event(
                "ratelimit.hit",
                level=logging.WARNING,
                client_ip=client_ip,
                method=method,
                path=path,
                surface=surface,
                listener=self.listener,
            )
