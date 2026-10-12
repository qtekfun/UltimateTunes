# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixtures of the web player tests: the real app over HTTPS from an Internet address (the web
player is not limited to the admin networks), the invented library of `tests/library`, the
fake catalog, and two plain users (`ana`, `bob`) whose passwords are made at run time."""

import re
import secrets
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tests.auth.conftest import fast_passwords, migrate_file
from tests.library.harness import seed_files
from ultimatetunes.admin.settings import AdminSettings
from ultimatetunes.app import AREAS, create_app
from ultimatetunes.auth.repository import User
from ultimatetunes.auth.service import AuthService
from ultimatetunes.auth.settings import AuthSettings
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.services import Services, build_services
from ultimatetunes.library.scan import LibraryScanner
from ultimatetunes.search.fake import FakeMusicCatalog
from ultimatetunes.settings import Settings
from ultimatetunes.web import web
from ultimatetunes.web.settings import WebSettings

OUTSIDE = ("203.0.113.7", 50000)
_TOKEN = re.compile(r'name="csrf" value="([^"]+)"')
_META = re.compile(r'<meta name="ut-csrf" content="([^"]+)">')


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def services(
    settings: Settings, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Services]:
    monkeypatch.setenv("UT_LIBRARY_SCAN_ON_START", "false")
    from ultimatetunes.library.web import library_settings  # noqa: PLC0415

    library_settings.cache_clear()
    migrate_file(settings.database_file)
    services = build_services(settings, clock)
    services.catalog = FakeMusicCatalog()
    services.authenticator = AuthService(
        services.db,
        clock,
        services.rate_limiter,
        AuthSettings(auth_lockout_s=60, auth_max_failures_per_user=3, auth_login_burst=50),
        fast_passwords(),
    )
    seed_files(settings.music_dir)
    LibraryScanner(services.db, services.library, clock).scan()
    yield services
    services.db.close()
    library_settings.cache_clear()


@pytest.fixture
def web_settings() -> WebSettings:
    return WebSettings(web_session_ttl_s=3600)


@pytest.fixture
def app_factory(
    services: Services, web_settings: WebSettings, monkeypatch: pytest.MonkeyPatch
) -> object:
    admin = AdminSettings(admin_session_secret=SecretStr(secrets.token_urlsafe(40)))

    class Hook:
        @staticmethod
        def install(app: object, svc: Services) -> None:
            web.install(app, svc, web_settings, admin)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "ultimatetunes.app.AREAS", tuple(Hook if area is web else area for area in AREAS)
    )
    return lambda: create_app(services=services)


def make_client(app_factory: object) -> TestClient:
    app = app_factory()  # type: ignore[operator]
    return TestClient(app, base_url="https://testserver", client=OUTSIDE, follow_redirects=False)


@pytest.fixture
def client(app_factory: object) -> Iterator[TestClient]:
    with make_client(app_factory) as test_client:
        yield test_client


@dataclass(frozen=True)
class Account:
    user: User
    password: str


@dataclass(frozen=True)
class People:
    ana: Account
    bob: Account


@pytest.fixture
def people(client: TestClient) -> People:
    auth: AuthService = client.app.state.web.auth  # type: ignore[attr-defined]
    accounts = []
    for name in ("ana", "bob"):
        password = secrets.token_urlsafe(18)
        accounts.append(Account(auth.create_user(name, password, "user", actor=None), password))
    return People(*accounts)


def csrf_of(html: str) -> str:
    found = _TOKEN.search(html) or _META.search(html)
    assert found, "no CSRF token in the page"
    return found.group(1)


def login(client: TestClient, account: Account) -> str:
    """Signs in through the form; returns the session's CSRF token."""
    form = client.get("/web/login")
    assert form.status_code == 200
    r = client.post(
        "/web/login",
        data={
            "csrf": csrf_of(form.text),
            "username": account.user.username,
            "password": account.password,
        },
    )
    assert r.status_code == 303, r.text
    assert r.headers["location"] == "/"
    return csrf_of(client.get("/web").text)


@pytest.fixture
def ana(client: TestClient, people: People) -> str:
    """Signs ana in; her CSRF token."""
    return login(client, people.ana)


def ids(services: Services) -> dict[str, str]:
    """Title → track id, artist name → artist id, album name → album id."""
    with services.db.read() as conn:
        rows = conn.execute(
            "SELECT title AS k, id FROM tracks UNION ALL SELECT name AS k, id FROM artists"
            " UNION ALL SELECT name AS k, id FROM albums"
        ).fetchall()
    return {str(r["k"]): str(r["id"]) for r in rows}
