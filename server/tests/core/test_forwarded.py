# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The client address behind reverse proxies (core/forwarded.py, T22)."""

import pytest
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.testclient import TestClient
from starlette.types import Receive, Scope, Send

from ultimatetunes.core.forwarded import (
    MAX_HOPS,
    TRUSTED_NETWORKS_STATE,
    UNKNOWN_CLIENT,
    ClientAddress,
    client_from_chain,
    from_trusted_network,
    resolve,
    trusted_origin,
    via_untrusted_proxy,
)
from ultimatetunes.core.netaddr import in_networks, parse_ip, parse_networks

PROXIES = parse_networks("127.0.0.1/32, 172.16.0.0/12")


def scope(peer: str | None, *headers: tuple[str, str]) -> Scope:
    return {
        "type": "http",
        "client": (peer, 1234) if peer else None,
        "headers": [(k.encode(), v.encode()) for k, v in headers],
    }


@pytest.mark.parametrize(
    ("chain", "client"),
    [
        (["203.0.113.9"], "203.0.113.9"),
        # Read from the right: what the client put on the left is not believed.
        (["10.0.0.1", "203.0.113.9"], "203.0.113.9"),
        # Trusted hops are skipped.
        (["203.0.113.9", "172.18.0.5"], "203.0.113.9"),
        # Only trusted proxies: the leftmost one started the chain.
        (["172.18.0.9", "127.0.0.1"], "172.18.0.9"),
        (["garbage", "203.0.113.9"], "203.0.113.9"),
        (["203.0.113.9", "not-an-ip"], UNKNOWN_CLIENT),
        ([], UNKNOWN_CLIENT),
        # Forged entries on the left are never read, however many (audit L1): a client that
        # prepends 31+ of them still is itself, not `unknown`.
        (["203.0.113.9"] * 33, "203.0.113.9"),
        ([*(f"10.9.0.{n}" for n in range(40)), "198.51.100.7"], "198.51.100.7"),
        ([*(["garbage"] * 50), "198.51.100.7", "172.18.0.2", "127.0.0.1"], "198.51.100.7"),
        (["::ffff:198.51.100.4"], "198.51.100.4"),
        # At most MAX_HOPS trusted hops in a row: one more and the client is unknown.
        ([*(["172.18.0.9"] * MAX_HOPS)], "172.18.0.9"),
        (["203.0.113.9", *(["172.18.0.9"] * MAX_HOPS)], "203.0.113.9"),
        (["203.0.113.9", *(["172.18.0.9"] * (MAX_HOPS + 1))], UNKNOWN_CLIENT),
    ],
)
def test_client_from_chain(chain: list[str], client: str) -> None:
    assert client_from_chain(chain, PROXIES) == client


def test_a_trusted_proxy_names_the_client() -> None:
    found = resolve(scope("172.18.0.1", ("X-Forwarded-For", "198.51.100.1, 203.0.113.9")), PROXIES)
    assert found["client"] == ("203.0.113.9", 0)
    assert not via_untrusted_proxy(found)
    # Several headers are one list.
    found = resolve(
        scope(
            "127.0.0.1",
            ("X-Forwarded-For", "203.0.113.9"),
            ("x-forwarded-for", "172.18.0.4"),
        ),
        PROXIES,
    )
    assert found["client"] == ("203.0.113.9", 0)


def test_a_long_forged_header_through_a_trusted_proxy_keeps_the_real_client() -> None:
    forged = ", ".join(f"192.168.1.{n}" for n in range(1, 41))
    found = resolve(scope("172.18.0.1", ("X-Forwarded-For", f"{forged}, 203.0.113.9")), PROXIES)
    assert found["client"] == ("203.0.113.9", 0)


def test_a_trusted_proxy_without_the_header_is_the_client() -> None:
    original = scope("172.18.0.1")
    assert resolve(original, PROXIES) is original


def test_an_untrusted_peer_is_the_client_and_its_forwarding_headers_mark_the_request() -> None:
    plain = scope("192.168.1.5")
    assert resolve(plain, PROXIES) is plain
    for name in ("X-Forwarded-For", "Forwarded", "X-Real-IP", "Tailscale-Funnel-Request"):
        found = resolve(scope("192.168.1.5", (name, "127.0.0.1")), PROXIES)
        assert found["client"] == ("192.168.1.5", 1234)
        assert via_untrusted_proxy(found)
    # No proxy configured at all (the default): every forwarded request is marked.
    assert via_untrusted_proxy(resolve(scope("127.0.0.1", ("X-Forwarded-For", "1.2.3.4")), ()))
    assert not via_untrusted_proxy(resolve(scope(None), ()))


def test_the_middleware_rewrites_http_scopes_only() -> None:
    async def echo(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":  # pragma: no cover - TestClient without `with`
            return
        request = Request(scope)
        host = request.client.host if request.client else None
        await JSONResponse({"host": host, "marked": via_untrusted_proxy(scope)})(
            scope, receive, send
        )

    app = ClientAddress(echo, PROXIES)
    behind = TestClient(app, client=("172.18.0.1", 1))
    assert behind.get("/", headers={"X-Forwarded-For": "203.0.113.9"}).json() == {
        "host": "203.0.113.9",
        "marked": False,
    }
    direct = TestClient(app, client=("192.168.1.5", 1))
    assert direct.get("/", headers={"X-Forwarded-For": "127.0.0.1"}).json() == {
        "host": "192.168.1.5",
        "marked": True,
    }


def test_address_helpers() -> None:
    assert parse_networks(" , ") == ()
    assert parse_ip(None) is None
    assert parse_ip("example.org") is None
    assert str(parse_ip("fe80::1%eth0")) == "fe80::1"
    assert in_networks("::ffff:127.0.0.1", PROXIES)
    assert not in_networks("::1", PROXIES)
    assert not in_networks(None, PROXIES)


LAN = parse_networks("192.168.0.0/16, 10.0.0.0/8")
WORKER = parse_networks("10.213.44.0/24")


@pytest.mark.parametrize(
    ("request_scope", "trusted"),
    [
        (scope("192.168.1.5"), True),
        (scope("203.0.113.9"), False),
        (scope(None), False),
        # The worker's network is private, yet never trusted.
        (scope("10.213.44.3"), False),
        (scope("10.1.2.3"), True),
        (resolve(scope("192.168.1.5", ("X-Forwarded-For", "192.168.1.6")), ()), False),
        (scope("192.168.1.5", ("Tailscale-Funnel-Request", "?1")), False),
    ],
)
def test_from_trusted_network(request_scope: Scope, trusted: bool) -> None:
    assert from_trusted_network(request_scope, LAN, WORKER) is trusted


def test_trusted_origin_needs_configured_networks() -> None:
    class State:
        pass

    holder = type("Holder", (), {"state": State()})()

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        request = Request({**scope, "app": holder})
        await JSONResponse({"trusted": trusted_origin(request)})(scope, receive, send)

    client = TestClient(app, client=("192.168.1.5", 1))
    assert client.get("/").json() == {"trusted": False}
    setattr(holder.state, TRUSTED_NETWORKS_STATE, (LAN, WORKER))
    assert client.get("/").json() == {"trusted": True}
