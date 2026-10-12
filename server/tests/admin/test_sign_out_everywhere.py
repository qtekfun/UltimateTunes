# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Users → "Sign out every device" in the panel (audit I4): admins only (the 403 of a non-admin
is in test_access.py), CSRF, a confirmation, any user's keys and sessions, audited."""

from fastapi.testclient import TestClient

from tests.admin.conftest import People, session_for
from ultimatetunes.auth.service import AuthService


def live_keys(auth: AuthService, user_id: str) -> int:
    return sum(1 for k in auth.list_keys(user_id) if k.revoked_at is None)


def test_an_admin_signs_out_every_device_of_a_user(
    client: TestClient, auth: AuthService, people: People, admin_csrf: str
) -> None:
    assert 'value="sign_out"' in client.get("/admin/users").text
    auth.create_key(people.bob.id, "bob phone", actor=None)
    alices = auth.create_key(people.alice.id, "alice phone", actor=None)
    url = f"/admin/users/{people.bob.id}"
    unconfirmed = client.post(url, data={"csrf": admin_csrf, "action": "sign_out"})
    assert unconfirmed.status_code == 400
    assert live_keys(auth, people.bob.id) == 1
    assert client.post(url, data={"action": "sign_out", "confirm": "yes"}).status_code == 403
    r = client.post(url, data={"csrf": admin_csrf, "action": "sign_out", "confirm": "yes"})
    assert r.status_code == 303
    assert r.headers["location"].endswith("done=user_signed_out")
    assert live_keys(auth, people.bob.id) == 0
    # The admin's own keys and session are untouched.
    assert auth.authenticate_api_key(alices.secret, None, "192.0.2.1").username == "alice"
    assert client.get("/admin/users").status_code == 200
    [entry] = [e for e in auth.recent_audit() if e.action == "user.sign_out_all"]
    assert (entry.actor_user_id, entry.target_id) == (people.alice.id, people.bob.id)


def test_an_admin_signing_out_their_own_account_ends_this_session_too(
    client: TestClient, auth: AuthService, people: People, admin_csrf: str
) -> None:
    url = f"/admin/users/{people.alice.id}"
    r = client.post(url, data={"csrf": admin_csrf, "action": "sign_out", "confirm": "yes"})
    assert r.status_code == 303
    assert client.get("/admin/users").status_code == 303  # back to the login form


def test_a_user_cannot_use_it(client: TestClient, auth: AuthService, people: People) -> None:
    auth.create_key(people.alice.id, "alice phone", actor=None)
    csrf = session_for(client, people.bob)
    r = client.post(
        f"/admin/users/{people.alice.id}",
        data={"csrf": csrf, "action": "sign_out", "confirm": "yes"},
    )
    assert r.status_code == 403
    assert live_keys(auth, people.alice.id) == 1
