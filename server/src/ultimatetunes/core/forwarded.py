# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Who the client really is behind a reverse proxy (SECURITY.md, T22).

`ClientAddress` is the outermost middleware of the api. Everything that looks at the client
address (admin allowlist, `/readyz` detail, the per-IP rate limit and lockout of T04, the audit
log) reads `scope["client"]`, so this is the one place that decides it:

- The TCP peer is inside `UT_TRUSTED_PROXIES`: `X-Forwarded-For` is read **from the right**,
  skipping hops that are trusted proxies too; the first other hop is the client, however many
  entries come before it. A hop on the way that is not an IP address, or more than `MAX_HOPS`
  trusted hops in a row, make the client `unknown` (no allowlist accepts it). Without the header the
  proxy itself is the client (its own health checks). `Forwarded` and `X-Real-IP` are ignored:
  one header, one rule.
- Any other peer is the client, whatever it sends. When it sends forwarding headers anyway, the
  request is marked (`VIA_UNTRUSTED_PROXY`): some proxy nobody configured stands in front
  (`tailscale serve`/Funnel or Caddy before `UT_TRUSTED_PROXIES` is set, where every caller
  looks local), so `/admin` refuses it and `/readyz` answers without detail. Failing closed is
  the default; setting `UT_TRUSTED_PROXIES` is how a proxied deployment opts in.

`from_trusted_network` is the one rule for "this request comes from the admin's own networks"
(LAN/Tailscale): the `/admin` allowlist and the separate per-user login lockout of
`AuthService.verify_password` (callers inside get their own counter, so strangers cannot lock
an admin out of LAN/Tailscale logins) both use it.
"""

from collections.abc import Iterable

from starlette.requests import HTTPConnection
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
# Set by Tailscale Funnel on public requests: never from a trusted network.
FUNNEL_HEADER = "tailscale-funnel-request"
# `app.state` attribute: `(networks, denied)` of `from_trusted_network` (the admin allowlist and
# the worker's networks, set by the admin area). Unset: no request comes from a trusted network.
TRUSTED_NETWORKS_STATE = "trusted_networks"


def via_untrusted_proxy(scope: Scope) -> bool:
    return bool(scope.get(VIA_UNTRUSTED_PROXY, False))


def from_trusted_network(
    scope: Scope, networks: tuple[IpNetwork, ...], denied: tuple[IpNetwork, ...] = ()
) -> bool:
    """The resolved client is inside `networks`, outside `denied`, and the request came neither
    through an untrusted proxy nor through Tailscale Funnel."""
    peer = scope.get("client")
    host = peer[0] if peer else None
    headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
    return (
        in_networks(host, networks)
        and not in_networks(host, denied)
        and not via_untrusted_proxy(scope)
        and not any(name.lower() == FUNNEL_HEADER.encode() for name, _ in headers)
    )


def trusted_origin(conn: HTTPConnection) -> bool:
    """`from_trusted_network` with the networks the app keeps in `TRUSTED_NETWORKS_STATE`."""
    configured: tuple[tuple[IpNetwork, ...], tuple[IpNetwork, ...]] | None = getattr(
        conn.app.state, TRUSTED_NETWORKS_STATE, None
    )
    if configured is None:
        return False
    networks, denied = configured
    return from_trusted_network(conn.scope, networks, denied)


def client_from_chain(hops: list[str], proxies: tuple[IpNetwork, ...]) -> str:
    """The client in an `X-Forwarded-For` chain whose last sender is a trusted proxy.

    Walked from the right; the first hop that is not a trusted proxy is the client, whatever
    comes before it (a client may prepend any number of forged entries: they are never read,
    so a long forged chain cannot turn the client `unknown`). `unknown` only when a hop on the
    way is not an IP address, or when more than `MAX_HOPS` trusted hops follow each other."""
    for trusted, hop in enumerate(reversed(hops), start=1):
        address = parse_ip(hop)
        if address is None:
            return UNKNOWN_CLIENT
        if not in_networks(str(address), proxies):
            return str(address)
        if trusted > MAX_HOPS:
            return UNKNOWN_CLIENT
    if not hops:
        return UNKNOWN_CLIENT
    # Every hop (at most MAX_HOPS) is a trusted proxy: the leftmost one started the chain.
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
