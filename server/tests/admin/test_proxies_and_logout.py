# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""T22 hardening of the panel: the allowlist behind reverse proxies (`UT_TRUSTED_PROXIES`,
Tailscale Funnel) and logout ending copied sessions (per-user session epoch)."""

from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.admin.conftest import People, login, session_for
from ultimatetunes.admin.routes import SESSION_EPOCH_KEY
from ultimatetunes.admin.security import SESSION_COOKIE
from ultimatetunes.core.services import Services

LOCAL = ("127.0.0.1", 40000)
DOCKER_GATEWAY = ("172.18.0.1", 40000)


def panel(app: FastAPI, peer: tuple[str, int]) -> TestClient:
    return TestClient(app, base_url="https://testserver", client=peer, follow_redirects=False)


@pytest.mark.parametrize(
    "header",
    [
        ("X-Forwarded-For", "203.0.113.9"),
        ("X-Forwarded-For", "192.168.1.5"),  # even a LAN address: nobody vouches for it
        ("Forwarded", "for=203.0.113.9"),
        ("X-Real-IP", "203.0.113.9"),
    ],
)
def test_an_unconfigured_proxy_in_front_is_refused(
    app_factory: Callable[[], FastAPI], header: tuple[str, str]
) -> None:
    """`tailscale serve`/Funnel or Caddy on the host: the peer looks local, yet the request
    came from somewhere else. Without `UT_TRUSTED_PROXIES` the panel fails closed."""
    with panel(app_factory(), LOCAL) as client:
        assert client.get("/admin/login").status_code == 200
        r = client.get("/admin/login", headers=dict([header]))
        assert (r.status_code, r.text) == (403, "Forbidden")
        assert "Content-Security-Policy" in r.headers


def test_tailscale_funnel_never_reaches_the_panel(
    app_factory: Callable[[], FastAPI], services: Services
) -> None:
    services.settings = services.settings.model_copy(update={"trusted_proxies": "127.0.0.1/32"})
    with panel(app_factory(), LOCAL) as client:
        r = client.get(
            "/admin/login",
            headers={"X-Forwarded-For": "100.100.1.2", "Tailscale-Funnel-Request": "?1"},
        )
        assert r.status_code == 403


def test_a_trusted_proxy_forwards_the_real_client(
    app_factory: Callable[[], FastAPI], services: Services
) -> None:
    services.settings = services.settings.model_copy(update={"trusted_proxies": "172.16.0.0/12"})
    with panel(app_factory(), DOCKER_GATEWAY) as client:
        # Tailnet and LAN callers through the proxy are in; the Internet is not.
        assert client.get("/admin/login", headers={"X-Forwarded-For": "100.90.1.2"}).is_success
        assert client.get("/admin/login", headers={"X-Forwarded-For": "192.168.1.5"}).is_success
        r = client.get("/admin/login", headers={"X-Forwarded-For": "203.0.113.9"})
        assert r.status_code == 403
        # A forged left part does not help: the proxy appends what it saw.
        r = client.get("/admin/login", headers={"X-Forwarded-For": "192.168.1.5, 203.0.113.9"})
        assert r.status_code == 403


def test_the_audit_log_records_the_forwarded_client(
    app_factory: Callable[[], FastAPI], services: Services, people: People
) -> None:
    services.settings = services.settings.model_copy(update={"trusted_proxies": "172.16.0.0/12"})
    with panel(app_factory(), DOCKER_GATEWAY) as client:
        client.headers["X-Forwarded-For"] = "192.168.1.77"
        login(client)
        with services.db.read() as conn:
            ip = conn.execute(
                "SELECT actor_ip FROM audit_log WHERE action = 'admin.login'"
            ).scalar()
    assert ip == "192.168.1.77"


def test_logout_ends_copied_sessions_too(
    client: TestClient, people: People, services: Services
) -> None:
    csrf = login(client)
    copied = client.cookies.get(SESSION_COOKIE)
    assert copied is not None
    assert client.post("/admin/logout", data={"csrf": csrf}).status_code == 303
    # Someone kept a copy of the cookie: it no longer works.
    client.cookies.set(SESSION_COOKIE, copied, domain="testserver.local", path="/admin")
    assert client.get("/admin").status_code == 303
    with services.db.read() as conn:
        epoch = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (SESSION_EPOCH_KEY + people.alice.id,)
        ).scalar()
    assert epoch == "1"
    # Signing in again works, and a second logout bumps the epoch again.
    csrf = login(client)
    assert client.get("/admin").status_code == 200
    assert client.post("/admin/logout", data={"csrf": csrf}).status_code == 303
    assert client.get("/admin").status_code == 303


def test_logout_of_one_admin_leaves_the_others_signed_in(
    client: TestClient, people: People, auth: object
) -> None:
    carol = client.app.state.admin.auth.create_user(  # type: ignore[attr-defined]
        "carol", "carol's long passphrase", "admin", actor=None
    )
    session_for(client, carol)
    carol_cookie = client.cookies.get(SESSION_COOKIE)
    client.cookies.clear()
    csrf = login(client)
    assert client.post("/admin/logout", data={"csrf": csrf}).status_code == 303
    client.cookies.set(SESSION_COOKIE, carol_cookie or "", domain="testserver.local", path="/admin")
    assert client.get("/admin").status_code == 200


def test_a_garbled_epoch_counts_as_zero(
    client: TestClient, people: People, services: Services
) -> None:
    with services.db.transaction() as conn:
        conn.execute(
            "INSERT INTO settings (key, value, updated_at)"
            " VALUES (?, 'x', '2026-01-01T00:00:00.000Z')",
            (SESSION_EPOCH_KEY + people.alice.id,),
        )
    session_for(client, people.alice)
    assert client.get("/admin").status_code == 200


def test_the_worker_network_never_reaches_the_panel(
    app_factory: Callable[[], FastAPI], services: Services
) -> None:
    """The worker's network is private, but a compromised worker must not get the panel."""
    services.settings = services.settings.model_copy(update={"worker_networks": "172.30.44.0/24"})
    app = app_factory()
    with panel(app, ("172.30.44.3", 40000)) as from_worker:
        assert from_worker.get("/admin/login").status_code == 403
    with panel(app, ("172.30.45.3", 40000)) as from_lan:
        assert from_lan.get("/admin/login").status_code == 200
