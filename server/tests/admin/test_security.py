# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Network allowlist, session cookie, login and logout, response headers (admin/security.py)."""

import ipaddress
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from tests.admin.conftest import SECRET, People, csrf_of, login, session_for
from tests.auth.conftest import ADMIN_PASSWORD, USER_PASSWORD
from ultimatetunes.admin.security import (
    CSP,
    LOGIN_COOKIE,
    MAX_BODY_BYTES,
    SESSION_COOKIE,
    SessionCodec,
    client_allowed,
)
from ultimatetunes.admin.settings import DEFAULT_ALLOWED_NETWORKS, AdminSettings, parse_networks
from ultimatetunes.core.clock import FakeClock

DEFAULT = parse_networks(DEFAULT_ALLOWED_NETWORKS)


# ---------------------------------------------------------------------- allowlist


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "::1",
        "10.1.2.3",
        "172.20.0.5",
        "192.168.1.20",
        "100.101.102.103",
        "fd7a:115c:a1e0::1",
        "fd00::5",
        "fe80::1%eth0",
        "::ffff:192.168.1.9",
    ],
)
def test_lan_and_tailscale_are_allowed(host: str) -> None:
    assert client_allowed(host, DEFAULT)


@pytest.mark.parametrize(
    "host",
    ["203.0.113.5", "8.8.8.8", "2001:db8::1", "::ffff:8.8.8.8", "testclient", "", None, "1.2.3"],
)
def test_everything_else_is_refused(host: str | None) -> None:
    assert not client_allowed(host, DEFAULT)


def test_opting_in_to_everywhere() -> None:
    everywhere = parse_networks("0.0.0.0/0, ::/0")
    assert client_allowed("203.0.113.5", everywhere)
    assert client_allowed("2001:db8::1", everywhere)


def test_settings_validate_networks_and_secret() -> None:
    assert AdminSettings().networks() == DEFAULT
    with pytest.raises(ValidationError):
        AdminSettings(admin_allowed_networks="10.0.0.0/8,not-a-network")
    with pytest.raises(ValidationError):
        AdminSettings(admin_allowed_networks=" , ")
    with pytest.raises(ValidationError):
        AdminSettings(admin_session_secret=SecretStr("short"))
    assert ipaddress.ip_network("100.64.0.0/10") in DEFAULT


@pytest.fixture
def outsider(app_factory: object) -> Iterator[TestClient]:
    app = app_factory()  # type: ignore[operator]
    with TestClient(
        app, base_url="https://testserver", client=("203.0.113.5", 4000), follow_redirects=False
    ) as test_client:
        yield test_client


def test_outside_the_allowlist_everything_under_admin_is_403(
    outsider: TestClient, people: People
) -> None:
    for path in ("/admin", "/admin/login", "/admin/static/htmx.min.js", "/admin/nope"):
        r = outsider.get(path)
        assert r.status_code == 403
        assert r.text == "Forbidden"
        assert r.headers["content-security-policy"] == CSP
    # Even with valid credentials and a real token from a LAN form, nothing passes.
    r = outsider.post(
        "/admin/login", data={"csrf": "x", "username": "alice", "password": ADMIN_PASSWORD}
    )
    assert r.status_code == 403
    # The home page (the web player's sign-in form) stays reachable.
    assert outsider.get("/").status_code == 200


def test_testclient_default_address_is_refused(app_factory: object) -> None:
    with TestClient(app_factory(), base_url="https://testserver") as plain:  # type: ignore[operator]
        assert plain.get("/admin/login").status_code == 403


def test_body_cap(client: TestClient, admin_csrf: str) -> None:
    big = client.post(
        "/admin/users", content=b"x" * (MAX_BODY_BYTES + 1), headers={"X-CSRF-Token": admin_csrf}
    )
    assert big.status_code == 413
    bad = client.post("/admin/users", content=b"x", headers={"content-length": "nope"})
    assert bad.status_code == 413

    def chunks() -> Iterator[bytes]:
        yield b"a=1"

    chunked = client.post("/admin/users", content=chunks())
    assert chunked.status_code == 413


def test_other_paths_are_untouched(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert "content-security-policy" not in r.headers


# ---------------------------------------------------------------------- headers


def test_security_headers_on_pages(client: TestClient, admin_csrf: str) -> None:
    for path in ("/admin", "/admin/login"):
        r = client.get(path)
        assert r.headers["content-security-policy"] == CSP
        assert r.headers["cache-control"] == "no-store"
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["referrer-policy"] == "no-referrer"
    static = client.get("/admin/static/admin.css")
    assert static.headers["cache-control"] == "max-age=3600"
    assert static.headers["content-security-policy"] == CSP


# ---------------------------------------------------------------------- login and session


def test_login_sets_a_strict_cookie(client: TestClient, people: People) -> None:
    form = client.get("/admin/login")
    login_cookie = form.headers["set-cookie"]
    assert LOGIN_COOKIE in login_cookie
    r = client.post(
        "/admin/login",
        data={"csrf": csrf_of(form.text), "username": "Alice", "password": ADMIN_PASSWORD},
    )
    assert r.status_code == 303
    cookies = r.headers.get_list("set-cookie")
    session = next(c for c in cookies if c.startswith(SESSION_COOKIE))
    for attribute in ("HttpOnly", "Secure", "SameSite=strict", "Path=/admin", "Max-Age=3600"):
        assert attribute.lower() in session.lower()
    assert any(c.startswith(LOGIN_COOKIE) and "Max-Age=0" in c for c in cookies)
    entries = client.app.state.admin.auth.recent_audit(5)  # type: ignore[attr-defined]
    assert "admin.login" in [e.action for e in entries]


def test_login_form_needs_its_token(client: TestClient, people: People) -> None:
    client.get("/admin/login")
    for token in ("", "forged"):
        r = client.post(
            "/admin/login", data={"csrf": token, "username": "alice", "password": ADMIN_PASSWORD}
        )
        assert r.status_code == 403
    form = client.get("/admin/login")
    r = client.post(
        "/admin/login",
        data={"csrf": csrf_of(form.text), "username": "alice", "password": ADMIN_PASSWORD},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert r.status_code == 403
    client.cookies.delete(LOGIN_COOKIE)
    r = client.post(
        "/admin/login",
        data={"csrf": csrf_of(form.text), "username": "alice", "password": ADMIN_PASSWORD},
    )
    assert r.status_code == 403


def test_login_errors(client: TestClient, people: People) -> None:
    def attempt(username: str, password: str) -> int:
        form = client.get("/admin/login")
        data = {"csrf": csrf_of(form.text), "username": username, "password": password}
        status: int = client.post("/admin/login", data=data).status_code
        return status

    assert attempt("alice", "wrong password!!") == 401
    assert attempt("nobody", "wrong password!!") == 401
    assert attempt("alice", "") == 400
    # bob's password is right, but he is not an admin: no session.
    form = client.get("/admin/login")
    r = client.post(
        "/admin/login",
        data={"csrf": csrf_of(form.text), "username": "bob", "password": USER_PASSWORD},
    )
    assert r.status_code == 403
    assert SESSION_COOKIE not in r.headers.get("set-cookie", "")
    # Per-username lockout (T04): three failures lock alice for a while.
    assert attempt("alice", "wrong password!!") == 401
    assert attempt("alice", "wrong password!!") == 401
    assert attempt("alice", ADMIN_PASSWORD) == 429


def test_logout_ends_the_session(client: TestClient, admin_csrf: str) -> None:
    r = client.post("/admin/logout", data={"csrf": admin_csrf})
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login"
    assert client.get("/admin").status_code == 303


def test_session_expires(client: TestClient, admin_csrf: str, clock: FakeClock) -> None:
    assert client.get("/admin").status_code == 200
    clock.advance(3601)
    assert client.get("/admin").status_code == 303


def test_password_change_and_disable_end_sessions(client: TestClient, people: People) -> None:
    auth = client.app.state.admin.auth  # type: ignore[attr-defined]
    login(client)
    auth.set_password(people.alice.id, "a brand new passphrase", actor=None)
    assert client.get("/admin").status_code == 303
    login(client, password="a brand new passphrase")
    auth.set_disabled(people.alice.id, True, actor=None)
    assert client.get("/admin").status_code == 303


def test_deleted_user_and_tampered_cookie(client: TestClient, people: People) -> None:
    session_for(client, people.alice)
    with client.app.state.services.db.transaction() as conn:  # type: ignore[attr-defined]
        conn.execute("DELETE FROM users WHERE id = ?", (people.alice.id,))
    assert client.get("/admin").status_code == 303
    client.cookies.set(SESSION_COOKIE, "garbage.value", domain="testserver.local", path="/admin")
    assert client.get("/admin").status_code == 303


def test_codec_rejects_foreign_and_malformed_tokens(clock: FakeClock) -> None:
    codec = SessionCodec(SECRET, clock, 60)
    other = SessionCodec("another-secret-another-secret-another", clock, 60)
    token, data = codec.new_session("u1", "hash")
    assert codec.read_session(token) == data
    assert other.read_session(token) is None
    assert codec.read_session(None) is None
    # Signed with the right key but not a session payload.
    assert codec.read_session(codec._session.dumps({"u": 1})) is None
    cookie, form_token = codec.new_login_token()
    assert codec.check_login_token(cookie, form_token)
    assert not codec.check_login_token(cookie, None)
    assert not codec.check_login_token("bad", form_token)
    assert not codec.check_login_token(codec._login.dumps(["x"]), "x")
    assert not codec.check_login_token(token, form_token)
    clock.advance(16 * 60)
    assert not codec.check_login_token(cookie, form_token)
    assert codec.fingerprint("a") != codec.fingerprint("b")


def test_random_session_key_without_a_secret(
    app_factory: object, admin_settings: AdminSettings, caplog: pytest.LogCaptureFixture
) -> None:
    object.__setattr__(admin_settings, "admin_session_secret", None)
    with TestClient(app_factory(), base_url="https://testserver", client=("10.0.0.2", 1)) as c:  # type: ignore[operator]
        assert c.get("/admin/login").status_code == 200
    assert "UT_ADMIN_SESSION_SECRET is not set" in caplog.text
