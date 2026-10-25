# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Who may use `/web`: sign-in, sessions and their revocation, CSRF, headers, limits."""

import secrets

import pytest
from fastapi.testclient import TestClient

from tests.web.conftest import People, csrf_of, login, make_client
from ultimatetunes.admin.routes import AdminState
from ultimatetunes.admin.security import SESSION_COOKIE as ADMIN_COOKIE
from ultimatetunes.auth.service import AuthService
from ultimatetunes.auth.settings import AuthSettings
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.web.routes import WebState
from ultimatetunes.web.security import CSP, SESSION_COOKIE
from ultimatetunes.web.settings import WebSettings

LAN = ("192.168.1.20", 50000)
UNKNOWN = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01ffff"
PAGES = [
    "/web",
    "/web/library",
    "/web/library/artists",
    "/web/library/playlists",
    "/web/library/favourites",
    "/web/search?q=lanterns",
    f"/web/album/{UNKNOWN}",
    f"/web/artist/{UNKNOWN}",
    f"/web/playlist/{UNKNOWN}",
    "/web/add/yt:Fk2Lp9QwXa1",
    "/web/radio",
    "/web/settings",
    "/web/imports",
    f"/web/imports/{UNKNOWN}",
]
CALLS = [
    "/web/api/radio/yt:Fk2Lp9QwXa1",
    "/web/api/lyrics/yt:Fk2Lp9QwXa1",
    "/web/api/status/yt:Fk2Lp9QwXa1",
    "/web/stream/yt:Fk2Lp9QwXa1",
    "/web/cover/yt:Fk2Lp9QwXa1",
    "/web/api/states?id=yt:Fk2Lp9QwXa1",
]
POSTS = [
    "/web/logout",
    "/web/star",
    "/web/playlists",
    f"/web/playlists/{UNKNOWN}/add",
    f"/web/playlists/{UNKNOWN}/remove",
    f"/web/playlists/{UNKNOWN}/delete",
    "/web/api/scrobble",
    "/web/api/request/yt:Fk2Lp9QwXa1",
    f"/web/playlists/{UNKNOWN}/rename",
    f"/web/playlists/{UNKNOWN}/move",
    "/web/settings/language",
    "/web/settings/password",
    f"/web/settings/keys/{UNKNOWN}/revoke",
    "/web/imports/url",
    "/web/imports/file",
]


def web_state(client: TestClient) -> WebState:
    found: WebState = client.app.state.web  # type: ignore[attr-defined]
    return found


def try_login(client: TestClient, username: str, password: str) -> int:
    form = client.get("/web/login")
    r = client.post(
        "/web/login",
        data={"csrf": csrf_of(form.text), "username": username, "password": password},
    )
    return int(r.status_code)


# ---------------------------------------------------------------------- without a session


@pytest.mark.parametrize("path", PAGES)
def test_pages_send_strangers_to_the_login_form(client: TestClient, path: str) -> None:
    r = client.get(path)
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    hx = client.get(path, headers={"HX-Request": "true"})
    assert hx.status_code == 200
    assert hx.headers["hx-redirect"] == "/"


@pytest.mark.parametrize("path", CALLS)
def test_player_calls_and_media_need_a_session(client: TestClient, path: str) -> None:
    r = client.get(path)
    assert r.status_code == 401
    assert r.json()["error"] == "authentication_required"


@pytest.mark.parametrize("path", POSTS)
def test_changes_need_a_session(client: TestClient, path: str) -> None:
    r = client.post(path, data={"csrf": "x"})
    assert r.status_code == 401
    hx = client.post(path, data={"csrf": "x"}, headers={"HX-Request": "true"})
    assert hx.status_code == 401
    assert hx.headers["hx-redirect"] == "/"


def test_a_forged_cookie_is_no_session(client: TestClient, people: People) -> None:
    client.cookies.set(SESSION_COOKIE, "forged.value", domain="testserver.local", path="/")
    assert client.get("/web").status_code == 303


def test_an_admin_cookie_is_not_a_web_cookie(client: TestClient, people: People) -> None:
    admin: AdminState = client.app.state.admin  # type: ignore[attr-defined]
    user = people.ana.user
    cookie, _data = admin.codec.new_session(user.id, user.password_hash)
    client.cookies.set(SESSION_COOKIE, cookie, domain="testserver.local", path="/")
    assert client.get("/web").status_code == 303
    client.cookies.set(ADMIN_COOKIE, cookie, domain="testserver.local", path="/admin")
    assert client.get("/web").status_code == 303


# ---------------------------------------------------------------------- sign in


def test_any_role_signs_in_from_anywhere_with_a_strict_cookie(
    client: TestClient, people: People
) -> None:
    form = client.get("/web/login")
    assert form.status_code == 200
    r = client.post(
        "/web/login",
        data={
            "csrf": csrf_of(form.text),
            "username": "ana",
            "password": people.ana.password,
        },
    )
    assert r.status_code == 303
    cookie = next(c for c in r.headers.get_list("set-cookie") if c.startswith(SESSION_COOKIE))
    lowered = cookie.lower()
    assert "httponly" in lowered
    assert "secure" in lowered
    assert "samesite=strict" in lowered
    assert "path=/;" in lowered or lowered.endswith("path=/")
    page = client.get("/web")
    assert page.status_code == 200
    assert "ana" in page.text
    # No secret of any kind in the page: no API key, no password.
    assert "utk_" not in page.text
    assert people.ana.password not in page.text


def test_wrong_passwords_and_bad_forms(client: TestClient, people: People) -> None:
    assert try_login(client, "ana", secrets.token_urlsafe(12)) == 401
    assert try_login(client, "nobody", secrets.token_urlsafe(12)) == 401
    assert try_login(client, "ana", "") == 400
    # No login token, or a cross-site post: refused before any password check.
    r = client.post("/web/login", data={"username": "ana", "password": people.ana.password})
    assert r.status_code == 403
    form = client.get("/web/login")
    r = client.post(
        "/web/login",
        data={"csrf": csrf_of(form.text), "username": "ana", "password": people.ana.password},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert r.status_code == 403


def test_a_disabled_user_cannot_sign_in_and_loses_the_session(
    client: TestClient, people: People
) -> None:
    login(client, people.ana)
    auth: AuthService = web_state(client).auth
    auth.set_disabled(people.ana.user.id, True, actor=None)
    assert client.get("/web").status_code == 303
    assert try_login(client, "ana", people.ana.password) == 401


def test_lockout_from_outside_never_locks_logins_from_the_lan(
    app_factory: object, people: People, clock: FakeClock
) -> None:
    """The same split counters as `POST /ut/v1/keys` (`AuthService.verify_password`): from
    outside a growing delay, never a long lockout (audit M1)."""
    with make_client(app_factory) as outside:
        for wait in (1, 2, 4):
            assert try_login(outside, "ana", secrets.token_urlsafe(12)) == 401
            assert try_login(outside, "ana", people.ana.password) == 429
            clock.advance(wait)
        assert try_login(outside, "ana", secrets.token_urlsafe(12)) == 401
        assert try_login(outside, "ana", people.ana.password) == 429
        app = outside.app
        with TestClient(
            app, base_url="https://testserver", client=LAN, follow_redirects=False
        ) as lan:
            assert try_login(lan, "ana", people.ana.password) == 303


# ---------------------------------------------------------------------- sign out and epochs


def test_logout_ends_every_session_of_the_user(app_factory: object, people: People) -> None:
    with make_client(app_factory) as laptop, make_client(app_factory) as phone:
        csrf = login(laptop, people.ana)
        login(phone, people.ana)
        copied = laptop.cookies.get(SESSION_COOKIE)
        assert copied
        r = laptop.post("/web/logout", data={"csrf": csrf})
        assert r.status_code == 303
        assert r.headers["location"] == "/"
        assert phone.get("/web").status_code == 303
        laptop.cookies.set(SESSION_COOKIE, copied, domain="testserver.local", path="/")
        assert laptop.get("/web").status_code == 303
        # Signing in again works (a new epoch).
        login(laptop, people.ana)
        assert laptop.get("/web").status_code == 200


def test_htmx_logout_reloads_the_login_page(client: TestClient, people: People) -> None:
    csrf = login(client, people.ana)
    r = client.post("/web/logout", data={"csrf": csrf}, headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert r.headers["hx-redirect"] == "/"


def test_a_new_password_ends_the_sessions(client: TestClient, people: People) -> None:
    login(client, people.ana)
    web_state(client).auth.set_password(people.ana.user.id, secrets.token_urlsafe(18), actor=None)
    assert client.get("/web").status_code == 303


def test_sessions_expire(client: TestClient, people: People, clock: FakeClock) -> None:
    login(client, people.ana)
    clock.advance(3601)
    assert client.get("/web").status_code == 303


def test_a_corrupt_epoch_counts_as_zero(client: TestClient, people: People) -> None:
    from ultimatetunes.admin.repository import AdminRepository  # noqa: PLC0415

    with web_state(client).services.db.transaction() as conn:
        AdminRepository(conn).put_setting(
            "web.session_epoch." + people.ana.user.id, "garbage", "2026-10-12T00:00:00.000Z"
        )
    login(client, people.ana)
    assert client.get("/web").status_code == 200


def test_a_deleted_user_loses_the_session(client: TestClient, people: People) -> None:
    login(client, people.ana)
    with web_state(client).services.db.transaction() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (people.ana.user.id,))
    assert client.get("/web").status_code == 303


# ---------------------------------------------------------------------- CSRF


def test_changes_need_the_session_csrf_token(client: TestClient, ana: str) -> None:
    form = {"kind": "song", "id": "yt:Fk2Lp9QwXa1", "on": "0"}
    assert client.post("/web/star", data=form).status_code == 403
    assert client.post("/web/star", data={**form, "csrf": "wrong"}).status_code == 403
    cross = client.post(
        "/web/star", data={**form, "csrf": ana}, headers={"Sec-Fetch-Site": "cross-site"}
    )
    assert cross.status_code == 403
    assert client.post("/web/star", data={**form, "csrf": ana}).status_code == 200
    # HTMX sends the token as a header.
    header = client.post("/web/star", data=form, headers={"X-CSRF-Token": ana})
    assert header.status_code == 200
    assert client.post("/web/logout", data={}).status_code == 403


# ---------------------------------------------------------------------- headers and limits


@pytest.mark.parametrize("path", ["/web/login", "/web/static/web.css", "/web/api/radio/x"])
def test_every_answer_carries_the_security_headers(client: TestClient, path: str) -> None:
    r = client.get(path)
    assert r.headers["content-security-policy"] == CSP
    assert "'unsafe-inline'" not in CSP
    assert "frame-ancestors 'none'" in CSP
    assert "manifest-src 'self'" in CSP
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"


def test_pages_are_never_cached_and_static_files_are(client: TestClient, ana: str) -> None:
    assert client.get("/web").headers["cache-control"] == "no-store"
    assert client.get("/web/login").headers["cache-control"] == "no-store"
    assert client.get("/web/static/player.js").headers["cache-control"] == "max-age=3600"


def test_other_paths_keep_their_headers(client: TestClient) -> None:
    assert "content-security-policy" not in client.get("/healthz").headers


def test_big_bodies_are_refused(client: TestClient, ana: str) -> None:
    r = client.post("/web/star", content=b"x" * (64 * 1024 + 1), headers={"X-CSRF-Token": ana})
    assert r.status_code == 413
    chunked = client.post(
        "/web/star",
        content=iter([b"kind=song"]),
        headers={"X-CSRF-Token": ana, "Content-Type": "application/x-www-form-urlencoded"},
    )
    assert chunked.status_code == 413
    bad = client.post("/web/star", content=b"x", headers={"Content-Length": "nope"})
    assert bad.status_code in (400, 413)


def test_the_request_rate_of_a_user_is_capped(client: TestClient, ana: str) -> None:
    web_state(client).auth_settings = AuthSettings(auth_key_rate_per_s=0.001, auth_key_burst=2)
    codes = [client.get("/web/library").status_code for _ in range(4)]
    assert codes[-1] == 429
    r = client.get("/web/library")
    assert r.status_code == 429
    assert "Retry-After" in r.headers
    api = client.get("/web/api/status/yt:Fk2Lp9QwXa1")
    assert api.status_code == 429
    assert api.json()["error"] == "rate_limited"


@pytest.mark.parametrize("web_settings", [WebSettings(web_enabled=False)])
def test_the_web_player_can_be_turned_off(app_factory: object, web_settings: WebSettings) -> None:
    with make_client(app_factory) as client:
        for path in ("/web", "/web/login", "/web/static/player.js"):
            r = client.get(path)
            assert r.status_code == 404
            assert r.headers["content-security-policy"] == CSP


@pytest.mark.parametrize("web_settings", [WebSettings(web_enabled=False)])
def test_turned_off_the_home_page_only_says_the_server_runs(
    app_factory: object, web_settings: WebSettings
) -> None:
    with make_client(app_factory) as client:
        r = client.get("/")
        assert r.status_code == 200
        assert "UltimateTunes server is running." in r.text
        assert "/admin" not in r.text
        assert "<form" not in r.text
        assert r.headers["content-security-policy"] == CSP


def test_every_web_route_is_covered_by_the_lists_above(client: TestClient) -> None:
    """A new route must be added to PAGES, CALLS or POSTS (and so be tested without a
    session)."""
    listed = {p.split("?", 1)[0] for p in PAGES + CALLS + POSTS}
    shapes = {_shape(p) for p in listed}
    public = {"/", "/web/login", "/web/static/{name}", "/web/", "/web/logout"}
    for route in client.app.routes:  # type: ignore[attr-defined]
        path = getattr(route, "path", "")
        if (path == "/" or path.startswith("/web")) and path not in public:
            assert _shape(path) in shapes, path


def _shape(path: str) -> str:
    parts = path.strip("/").split("/")
    return "/".join("{}" if (p.startswith("{") or "-" in p or ":" in p) else p for p in parts)


def test_a_stranger_only_slows_down_the_web_sign_in_of_a_family_member(
    app_factory: object, people: People, clock: FakeClock
) -> None:
    """Audit M1 (final): many wrong passwords from the Internet never lock a username for long;
    once the current delay (at most `auth_outside_backoff_max_s`) is over, the right password
    signs in from outside too, and that success resets the delay."""
    with make_client(app_factory) as stranger, make_client(app_factory) as family:
        for _ in range(8):
            assert try_login(stranger, "ana", secrets.token_urlsafe(12)) == 401
            clock.advance(400)
        assert try_login(family, "ana", people.ana.password) == 303
        assert try_login(stranger, "ana", secrets.token_urlsafe(12)) == 401
        clock.advance(1)
        assert try_login(make_client(app_factory), "ana", people.ana.password) == 303
