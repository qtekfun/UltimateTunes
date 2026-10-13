# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The panel's security events: refused networks, non-admins, CSRF, unusable sessions and
sign-ins, each with the resolved client address (docs/logging.md)."""

import secrets
from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.admin.conftest import LAN, People, csrf_of, login, session_for
from tests.auth.conftest import ADMIN_PASSWORD
from tests.security_events import Events, rendered
from ultimatetunes.admin import routes
from ultimatetunes.admin.security import SESSION_COOKIE
from ultimatetunes.auth.service import AuthService
from ultimatetunes.core.services import Services

LOCAL = ("127.0.0.1", 40000)


def panel(app: FastAPI, peer: tuple[str, int]) -> TestClient:
    return TestClient(app, base_url="https://testserver", client=peer, follow_redirects=False)


def test_outside_the_allowlist(app_factory: Callable[[], FastAPI], events: Events) -> None:
    with panel(app_factory(), ("203.0.113.9", 40000)) as outsider:
        assert outsider.get("/admin/login").status_code == 403
    (denied,) = events("access.denied")
    assert denied == {
        "event": "access.denied",
        "reason": "network",
        "client_ip": "203.0.113.9",
        "surface": "admin",
        "method": "GET",
        "path": "/admin/login",
    }


def test_an_unconfigured_proxy(app_factory: Callable[[], FastAPI], events: Events) -> None:
    with panel(app_factory(), LOCAL) as client:
        client.get("/admin/login", headers={"X-Forwarded-For": "203.0.113.9"})
    (denied,) = events("access.denied")
    assert (denied["reason"], denied["client_ip"]) == ("untrusted_proxy", "127.0.0.1")


def test_behind_a_trusted_proxy_the_real_client_is_logged(
    app_factory: Callable[[], FastAPI], services: Services, events: Events
) -> None:
    services.settings = services.settings.model_copy(update={"trusted_proxies": "127.0.0.1/32"})
    with panel(app_factory(), LOCAL) as client:
        client.get("/admin/login", headers={"X-Forwarded-For": "198.51.100.20"})
        client.get(
            "/admin/login",
            headers={"X-Forwarded-For": "100.100.1.2", "Tailscale-Funnel-Request": "?1"},
        )
    outside, funnel = events("access.denied")
    assert (outside["reason"], outside["client_ip"]) == ("network", "198.51.100.20")
    assert (funnel["reason"], funnel["client_ip"]) == ("funnel", "100.100.1.2")


def test_the_worker_network(
    app_factory: Callable[[], FastAPI], services: Services, events: Events
) -> None:
    services.settings = services.settings.model_copy(update={"worker_networks": "172.30.44.0/24"})
    with panel(app_factory(), ("172.30.44.3", 40000)) as worker:
        worker.get("/admin/login")
    (denied,) = events("access.denied")
    assert (denied["reason"], denied["client_ip"]) == ("worker_network", "172.30.44.3")


def test_sign_ins(
    client: TestClient, people: People, events: Events, caplog: pytest.LogCaptureFixture
) -> None:
    form = client.get("/admin/login")
    wrong = secrets.token_urlsafe(16)
    client.post(
        "/admin/login", data={"csrf": csrf_of(form.text), "username": "alice", "password": wrong}
    )
    login(client)
    (failure,) = events("auth.failure")
    assert (failure["reason"], failure["user"], failure["surface"]) == (
        "bad_password",
        "alice",
        "admin",
    )
    assert (failure["client_ip"], failure["trusted"]) == (LAN[0], True)
    success = events("auth.success")[-1]
    assert (success["user"], success["surface"], success["path"]) == (
        "alice",
        "admin",
        "/admin/login",
    )
    assert "admin.login" in [e["action"] for e in events("audit")]
    out = rendered(caplog)
    assert wrong not in out
    assert ADMIN_PASSWORD not in out


def test_a_user_who_is_not_an_admin(client: TestClient, people: People, events: Events) -> None:
    session_for(client, people.bob)
    assert client.get("/admin").status_code == 403
    (denied,) = events("access.denied")
    assert (denied["reason"], denied["user"], denied["client_ip"]) == ("not_admin", "bob", LAN[0])


def test_the_login_form_refuses_a_non_admin(
    client: TestClient, auth: AuthService, people: People, events: Events
) -> None:
    password = secrets.token_urlsafe(16)
    auth.set_password(people.bob.id, password, actor=None)
    form = client.get("/admin/login")
    r = client.post(
        "/admin/login", data={"csrf": csrf_of(form.text), "username": "bob", "password": password}
    )
    assert r.status_code == 403
    (denied,) = events("access.denied")
    assert (denied["reason"], denied["user"]) == ("not_admin", "bob")


def test_csrf_failures(client: TestClient, admin_csrf: str, events: Events) -> None:
    client.post("/admin/users", data={"csrf": admin_csrf[:-1] + "x"})
    client.post("/admin/users", data={"csrf": admin_csrf}, headers={"Sec-Fetch-Site": "cross-site"})
    client.post("/admin/login", data={"csrf": "forged", "username": "a", "password": "b"})
    client.post(
        "/admin/login",
        data={"csrf": "forged", "username": "a", "password": "b"},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert [(e["reason"], e["path"]) for e in events("csrf.failure")] == [
        ("token", "/admin/users"),
        ("cross_site", "/admin/users"),
        ("login_token", "/admin/login"),
        ("cross_site", "/admin/login"),
    ]


def test_unusable_sessions(
    client: TestClient, auth: AuthService, people: People, events: Events
) -> None:
    client.cookies.set(SESSION_COOKIE, "forged", domain="testserver.local", path="/admin")
    client.get("/admin")
    state: routes.AdminState = client.app.state.admin  # type: ignore[attr-defined]
    ghost, _ = state.codec.new_session("no-such-user", "x")
    client.cookies.set(SESSION_COOKIE, ghost, domain="testserver.local", path="/admin")
    client.get("/admin")
    csrf = login(client)
    copied = client.cookies.get(SESSION_COOKIE)
    client.post("/admin/logout", data={"csrf": csrf})
    assert copied is not None
    client.cookies.set(SESSION_COOKIE, copied, domain="testserver.local", path="/admin")
    client.get("/admin")
    session_for(client, people.alice)
    auth.set_disabled(people.alice.id, True, actor=None)
    client.get("/admin")
    assert [(e["reason"], e.get("user")) for e in events("session.rejected")] == [
        ("invalid_or_expired", None),
        ("unknown_user", None),
        ("revoked", "alice"),
        ("account_disabled", "alice"),
    ]
    # No cookie at all is not an event: a first visit.
    client.cookies.clear()
    client.get("/admin")
    assert len(events("session.rejected")) == 4
