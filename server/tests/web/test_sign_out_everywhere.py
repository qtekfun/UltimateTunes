# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings → "Sign out every device" (audit I4): CSRF, confirmation, own account only, every
key and every session of the user ended, audited."""

from fastapi.testclient import TestClient

from tests.web.conftest import People, login, make_client
from ultimatetunes.auth.service import AuthService
from ultimatetunes.web.security import SESSION_COOKIE

URL = "/web/settings/sign-out-everywhere"


def auth_of(client: TestClient) -> AuthService:
    service: AuthService = client.app.state.web.auth  # type: ignore[attr-defined]
    return service


def live_keys(auth: AuthService, user_id: str) -> int:
    return sum(1 for k in auth.list_keys(user_id) if k.revoked_at is None)


def test_the_settings_page_offers_it(client: TestClient, ana: str) -> None:
    page = client.get("/web/settings")
    assert f'action="{URL}"' in page.text
    assert 'name="confirm" value="yes" required' in page.text


def test_it_needs_the_csrf_token_and_the_confirmation(app_factory: object, people: People) -> None:
    with make_client(app_factory) as laptop:
        csrf = login(laptop, people.ana)
        auth = auth_of(laptop)
        auth.create_key(people.ana.user.id, "ana phone", actor=None)
        assert laptop.post(URL, data={"confirm": "yes"}).status_code == 403
        assert laptop.post(URL, data={"csrf": "wrong", "confirm": "yes"}).status_code == 403
        r = laptop.post(URL, data={"csrf": csrf})
        assert r.status_code == 400
        assert "Tick the box" in r.text
        # Nothing happened.
        assert live_keys(auth, people.ana.user.id) == 1
        assert laptop.get("/web/settings").status_code == 200


def test_it_ends_every_key_and_session_of_the_caller_only(
    app_factory: object, people: People
) -> None:
    with make_client(app_factory) as laptop, make_client(app_factory) as phone:
        csrf = login(laptop, people.ana)
        login(phone, people.ana)
        copied = laptop.cookies.get(SESSION_COOKIE)
        auth = auth_of(laptop)
        for name in ("ana phone", "ana tablet"):
            auth.create_key(people.ana.user.id, name, actor=None)
        bobs = auth.create_key(people.bob.user.id, "bob phone", actor=None)
        # A user id in the form is ignored: only the caller's own account (no IDOR).
        r = laptop.post(URL, data={"csrf": csrf, "confirm": "yes", "user_id": people.bob.user.id})
        assert r.status_code == 303
        assert r.headers["location"] == "/"
        assert f"{SESSION_COOKIE}=" in r.headers["set-cookie"]
        assert live_keys(auth, people.ana.user.id) == 0
        assert live_keys(auth, people.bob.user.id) == 1
        assert auth.authenticate_api_key(bobs.secret, None, "192.0.2.1").username == "bob"
        # Every session of ana is over, this one, the other browser and copied cookies too.
        assert phone.get("/web/settings").status_code == 303
        assert copied
        laptop.cookies.set(SESSION_COOKIE, copied, domain="testserver.local", path="/")
        assert laptop.get("/web/settings").status_code == 303
        [entry] = [e for e in auth.recent_audit() if e.action == "user.sign_out_all"]
        assert (entry.actor_user_id, entry.target_id) == (people.ana.user.id, people.ana.user.id)
        # Signing in again works.
        login(laptop, people.ana)


def test_htmx_gets_a_full_reload(client: TestClient, ana: str) -> None:
    r = client.post(URL, data={"csrf": ana, "confirm": "yes"}, headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert r.headers["hx-redirect"] == "/"


def test_it_needs_a_session(client: TestClient, people: People) -> None:
    assert client.post(URL, data={"confirm": "yes"}).status_code in (401, 403)
