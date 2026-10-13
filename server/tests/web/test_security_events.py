# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The web player's and `POST /ut/v1/keys`' security events (docs/logging.md)."""

import secrets

import pytest
from fastapi.testclient import TestClient

from tests.security_events import Events, rendered
from tests.web.conftest import OUTSIDE, People, csrf_of, login
from ultimatetunes.auth.service import AuthService
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.web.routes import WebState
from ultimatetunes.web.security import SESSION_COOKIE


def web_state(client: TestClient) -> WebState:
    found: WebState = client.app.state.web  # type: ignore[attr-defined]
    return found


def test_web_sign_ins(
    client: TestClient,
    people: People,
    clock: FakeClock,
    events: Events,
    caplog: pytest.LogCaptureFixture,
) -> None:
    wrong = secrets.token_urlsafe(16)
    form = client.get("/web/login")
    r = client.post(
        "/web/login", data={"csrf": csrf_of(form.text), "username": "ana", "password": wrong}
    )
    assert r.status_code == 401
    clock.advance(2)  # the outside delay of one failure
    login(client, people.ana)
    (failure,) = events("auth.failure")
    assert failure == {
        "event": "auth.failure",
        "reason": "bad_password",
        "client_ip": OUTSIDE[0],
        "surface": "web",
        "method": "POST",
        "path": "/web/login",
        "user": "ana",
        "known_user": True,
        "trusted": False,
        "credential": "password",
    }
    success = events("auth.success")[-1]
    assert (success["user"], success["surface"]) == ("ana", "web")
    assert "web.login" in [e["action"] for e in events("audit")]
    out = rendered(caplog)
    assert wrong not in out
    assert people.ana.password not in out


def test_password_key_requests(client: TestClient, people: People, events: Events) -> None:
    wrong = secrets.token_urlsafe(16)
    r = client.post("/ut/v1/keys", json={"username": "bob", "password": wrong, "name": "phone"})
    assert r.status_code == 401
    (failure,) = events("auth.failure")
    assert (failure["surface"], failure["user"], failure["client_ip"]) == (
        "ut_keys",
        "bob",
        OUTSIDE[0],
    )


def test_csrf_failures(client: TestClient, ana: str, events: Events) -> None:
    form = {"kind": "song", "id": "yt:Fk2Lp9QwXa1", "on": "0"}
    client.post("/web/star", data={**form, "csrf": "wrong"})
    client.post("/web/login", data={"csrf": "forged", "username": "a", "password": "b"})
    assert [(e["reason"], e["path"]) for e in events("csrf.failure")] == [
        ("token", "/web/star"),
        ("login_token", "/web/login"),
    ]


def test_unusable_sessions(client: TestClient, people: People, events: Events) -> None:
    client.cookies.set(SESSION_COOKIE, "forged.value", domain="testserver.local", path="/")
    client.get("/web")
    ghost, _ = web_state(client).codec.new_session("no-such-user", "x")
    client.cookies.set(SESSION_COOKIE, ghost, domain="testserver.local", path="/")
    client.get("/web")
    login(client, people.bob)
    copied = client.cookies.get(SESSION_COOKIE)
    assert copied is not None
    auth: AuthService = web_state(client).auth
    auth.set_password(people.bob.user.id, secrets.token_urlsafe(16), actor=None)
    client.get("/web")
    login(client, people.ana)
    auth.set_disabled(people.ana.user.id, True, actor=None)
    client.get("/web")
    assert [(e["reason"], e.get("user")) for e in events("session.rejected")] == [
        ("invalid_or_expired", None),
        ("unknown_user", None),
        ("revoked", "bob"),
        ("account_disabled", "ana"),
    ]
