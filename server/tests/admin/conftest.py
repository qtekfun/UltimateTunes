# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixtures of the admin panel tests: the real app over HTTPS from a LAN address, an admin
(`alice`) and a plain user (`bob`), and helpers to sign in and to read CSRF tokens."""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tests.auth.conftest import ADMIN_PASSWORD, USER_PASSWORD, fast_passwords, migrate_file
from ultimatetunes.admin import routes, web
from ultimatetunes.admin.notify import Sender
from ultimatetunes.admin.security import SESSION_COOKIE
from ultimatetunes.admin.settings import AdminSettings
from ultimatetunes.app import AREAS, create_app
from ultimatetunes.auth.repository import User
from ultimatetunes.auth.service import AuthService
from ultimatetunes.auth.settings import AuthSettings
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.services import Services, build_services
from ultimatetunes.settings import Settings

LAN = ("192.168.1.20", 50000)
SECRET = "test-admin-session-secret-0123456789abcdef"
_TOKEN = re.compile(r'name="csrf" value="([^"]+)"')


@pytest.fixture
def settings_music(settings: Settings) -> Path:
    return settings.music_dir


@pytest.fixture
def admin_settings() -> AdminSettings:
    return AdminSettings(admin_session_secret=SecretStr(SECRET), admin_session_ttl_s=3600)


@pytest.fixture
def services(settings: Settings, clock: FakeClock) -> Iterator[Services]:
    migrate_file(settings.database_file)
    services = build_services(settings, clock)
    services.authenticator = AuthService(
        services.db,
        clock,
        services.rate_limiter,
        AuthSettings(auth_lockout_s=60, auth_max_failures_per_user=3, auth_login_burst=50),
        fast_passwords(),
    )
    yield services
    services.db.close()


class RecordingTransport(httpx.AsyncBaseTransport):
    """Answers every outbound notification with `status` and remembers the requests."""

    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        await request.aread()
        return httpx.Response(self.status)


async def public_dns(host: str) -> list[str]:
    """Fake resolver of the notification tests: every name is a public address (no DNS)."""
    return ["203.0.113.80"]


@pytest.fixture
def transport() -> RecordingTransport:
    return RecordingTransport()


@pytest.fixture
def app_factory(
    services: Services,
    admin_settings: AdminSettings,
    transport: RecordingTransport,
    monkeypatch: pytest.MonkeyPatch,
) -> object:
    """`create_app` with the admin area installed with test settings and a fake transport."""

    class Hook:
        @staticmethod
        def install(app: object, svc: Services) -> None:
            web.install(app, svc, admin_settings, Sender(transport, public_dns))  # type: ignore[arg-type]

    monkeypatch.setattr(
        "ultimatetunes.app.AREAS", tuple(Hook if area is web else area for area in AREAS)
    )
    return lambda: create_app(services=services)


@pytest.fixture
def client(app_factory: object) -> Iterator[TestClient]:
    app = app_factory()  # type: ignore[operator]
    with TestClient(
        app, base_url="https://testserver", client=LAN, follow_redirects=False
    ) as test_client:
        yield test_client


@pytest.fixture
def auth(client: TestClient) -> AuthService:
    service = client.app.state.admin.auth  # type: ignore[attr-defined]
    assert isinstance(service, AuthService)
    return service


@dataclass(frozen=True)
class People:
    alice: User
    bob: User


@pytest.fixture
def people(auth: AuthService) -> People:
    alice = auth.create_user("alice", ADMIN_PASSWORD, "admin", actor=None)
    bob = auth.create_user("bob", USER_PASSWORD, "user", actor=None)
    return People(alice, bob)


def csrf_of(html: str) -> str:
    found = _TOKEN.search(html)
    assert found, "no CSRF field in the page"
    return found.group(1)


def login(client: TestClient, username: str = "alice", password: str = ADMIN_PASSWORD) -> str:
    """Signs in through the form and returns the session's CSRF token."""
    form = client.get("/admin/login")
    assert form.status_code == 200
    r = client.post(
        "/admin/login",
        data={"csrf": csrf_of(form.text), "username": username, "password": password},
    )
    assert r.status_code == 303, r.text
    assert r.headers["location"] == "/admin"
    page = client.get("/admin/users")
    return csrf_of(page.text)


@pytest.fixture
def admin_csrf(client: TestClient, people: People) -> str:
    return login(client)


def session_for(client: TestClient, user: User) -> str:
    """A valid session cookie for any user (bob cannot sign in: he is not an admin). Returns
    its CSRF token."""
    state: routes.AdminState = client.app.state.admin  # type: ignore[attr-defined]
    cookie, data = state.codec.new_session(user.id, user.password_hash)
    client.cookies.set(SESSION_COOKIE, cookie, domain="testserver.local", path="/admin")
    return data.csrf


def db_user(auth: AuthService, user_id: str) -> User:
    return auth.get_user(user_id)


__all__ = ["USER_PASSWORD"]
