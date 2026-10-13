# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every admin route, enumerated from the router itself (a new route is covered without
editing this file): 403 for a user who is not an admin, 403 without a session on state changes
(a redirect to the login form on pages), and 403 on every state change without the right CSRF
token or from another site (CLAUDE.md security rules, PLAN T15 verification)."""

import re

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from tests.admin.conftest import People, session_for
from ultimatetunes.admin import routes

# Reachable without a session (inside the allowlist): the login form, its second-factor step
# and the two static files.
PUBLIC = {
    ("GET", "/admin/login"),
    ("POST", "/admin/login"),
    ("POST", "/admin/login/2fa"),
    ("GET", "/admin/static/{name}"),
}
SAMPLE = {
    "user_id": "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c001",
    "key_id": "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c002",
    "job_id": "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c003",
    "item_id": "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c004",
    "kind": "tracks",
    "command": "update",
}


def _all_routes() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for route in routes.router.routes:
        assert isinstance(route, APIRoute)
        found.extend((method, route.path) for method in sorted(route.methods or ()))
    return found


def _url(path: str) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: SAMPLE[m.group(1)], path)


PROTECTED = [r for r in _all_routes() if r not in PUBLIC]
PAGES = [(m, p) for m, p in PROTECTED if m == "GET"]
CHANGES = [(m, p) for m, p in PROTECTED if m == "POST"]


def test_the_route_lists_are_complete() -> None:
    assert len(PAGES) >= 9
    assert len(CHANGES) >= 11
    assert {m for m, _ in PROTECTED} == {"GET", "POST"}
    assert set(_all_routes()) >= PUBLIC


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_non_admin_gets_403(client: TestClient, people: People, method: str, path: str) -> None:
    csrf = session_for(client, people.bob)
    r = client.request(method, _url(path), data={"csrf": csrf} if method == "POST" else None)
    assert r.status_code == 403
    assert "not an administrator" in r.text


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_demoted_admin_gets_403(client: TestClient, people: People, method: str, path: str) -> None:
    csrf = session_for(client, people.alice)
    client.app.state.admin.auth.set_role(people.alice.id, "user", actor=None)  # type: ignore[attr-defined]
    r = client.request(method, _url(path), data={"csrf": csrf} if method == "POST" else None)
    assert r.status_code == 403


@pytest.mark.parametrize(("method", "path"), PAGES)
def test_pages_without_session_redirect_to_login(
    client: TestClient, method: str, path: str
) -> None:
    r = client.get(_url(path))
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login"
    htmx = client.get(_url(path), headers={"HX-Request": "true"})
    assert htmx.status_code == 200
    assert htmx.headers["hx-redirect"] == "/admin/login"


@pytest.mark.parametrize(("method", "path"), CHANGES)
def test_changes_without_session_get_403(client: TestClient, method: str, path: str) -> None:
    r = client.post(_url(path), data={"csrf": "anything"})
    assert r.status_code == 403


@pytest.mark.parametrize(("method", "path"), CHANGES)
def test_changes_need_the_csrf_token(
    client: TestClient, people: People, method: str, path: str
) -> None:
    csrf = session_for(client, people.alice)
    assert client.post(_url(path)).status_code == 403
    assert client.post(_url(path), data={"csrf": csrf[:-1] + "x"}).status_code == 403
    cross = client.post(_url(path), data={"csrf": csrf}, headers={"Sec-Fetch-Site": "cross-site"})
    assert cross.status_code == 403
    assert "another site" in cross.text
    # The header HTMX sends is accepted in place of the form field.
    via_header = client.post(_url(path), headers={"X-CSRF-Token": csrf})
    assert via_header.status_code != 403


def test_a_session_of_one_admin_is_not_valid_csrf_for_another(
    client: TestClient, people: People
) -> None:
    other = client.app.state.admin.auth.create_user(  # type: ignore[attr-defined]
        "carol", "yet another long passphrase", "admin", actor=None
    )
    stale = session_for(client, people.alice)
    session_for(client, other)
    r = client.post(
        "/admin/users",
        data={"csrf": stale, "username": "dave", "password": "p" * 12, "role": "user"},
    )
    assert r.status_code == 403
