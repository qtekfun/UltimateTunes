# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The client address behind reverse proxies (core/forwarded.py, T22)."""

import pytest
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.testclient import TestClient
from starlette.types import Receive, Scope, Send

from ultimatetunes.core.forwarded import (
    UNKNOWN_CLIENT,
    ClientAddress,
    client_from_chain,
    resolve,
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
        (["203.0.113.9"] * 33, UNKNOWN_CLIENT),
        (["::ffff:198.51.100.4"], "198.51.100.4"),
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
