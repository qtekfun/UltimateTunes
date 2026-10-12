# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Who the client really is behind a reverse proxy (SECURITY.md, T22).

`ClientAddress` is the outermost middleware of the api. Everything that looks at the client
address (admin allowlist, `/readyz` detail, the per-IP rate limit and lockout of T04, the audit
log) reads `scope["client"]`, so this is the one place that decides it:

- The TCP peer is inside `UT_TRUSTED_PROXIES`: `X-Forwarded-For` is read **from the right**,
  skipping hops that are trusted proxies too; the first other hop is the client. A hop that is
  not an IP address makes the client `unknown` (no allowlist accepts it). Without the header the
  proxy itself is the client (its own health checks). `Forwarded` and `X-Real-IP` are ignored:
  one header, one rule.
- Any other peer is the client, whatever it sends. When it sends forwarding headers anyway, the
  request is marked (`VIA_UNTRUSTED_PROXY`): some proxy nobody configured stands in front
  (`tailscale serve`/Funnel or Caddy before `UT_TRUSTED_PROXIES` is set, where every caller
  looks local), so `/admin` refuses it and `/readyz` answers without detail. Failing closed is
  the default; setting `UT_TRUSTED_PROXIES` is how a proxied deployment opts in.
"""

from collections.abc import Iterable

from starlette.types import ASGIApp, Receive, Scope, Send

from ultimatetunes.core.netaddr import IpNetwork, in_networks, parse_ip

VIA_UNTRUSTED_PROXY = "ultimatetunes.via_untrusted_proxy"
UNKNOWN_CLIENT = "unknown"
# Headers a reverse proxy adds; their presence from an untrusted peer marks the request.
FORWARDING_HEADERS = frozenset(
    {
        b"forwarded",
        b"x-forwarded-for",
        b"x-forwarded-host",
        b"x-forwarded-proto",
        b"x-real-ip",
        b"tailscale-funnel-request",
    }
)
MAX_HOPS = 32


def via_untrusted_proxy(scope: Scope) -> bool:
    return bool(scope.get(VIA_UNTRUSTED_PROXY, False))


def client_from_chain(hops: list[str], proxies: tuple[IpNetwork, ...]) -> str:
    """The client in an `X-Forwarded-For` chain whose last sender is a trusted proxy."""
    if not hops or len(hops) > MAX_HOPS:
        return UNKNOWN_CLIENT
    for hop in reversed(hops):
        address = parse_ip(hop)
        if address is None:
            return UNKNOWN_CLIENT
        if not in_networks(str(address), proxies):
            return str(address)
    # Every hop is a trusted proxy: the leftmost one started the chain.
    return str(parse_ip(hops[0]))


def _forwarded_for(headers: Iterable[tuple[bytes, bytes]]) -> list[str] | None:
    values = [v.decode("latin-1") for k, v in headers if k.lower() == b"x-forwarded-for"]
    if not values:
        return None
    return [hop.strip() for value in values for hop in value.split(",")]


def resolve(scope: Scope, proxies: tuple[IpNetwork, ...]) -> Scope:
    """The scope with the real client (a copy when anything changes)."""
    headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
    peer = scope.get("client")
    host = peer[0] if peer else None
    if not in_networks(host, proxies):
        if any(name.lower() in FORWARDING_HEADERS for name, _ in headers):
            return {**scope, VIA_UNTRUSTED_PROXY: True}
        return scope
    hops = _forwarded_for(headers)
    if hops is None:
        return scope
    return {**scope, "client": (client_from_chain(hops, proxies), 0)}


class ClientAddress:
    """Plain ASGI middleware: rewrites `scope["client"]` as described above."""

    def __init__(self, app: ASGIApp, proxies: tuple[IpNetwork, ...]) -> None:
        self._app = app
        self._proxies = proxies

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            scope = resolve(scope, self._proxies)
        await self._app(scope, receive, send)
