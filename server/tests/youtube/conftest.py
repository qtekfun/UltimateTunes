# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixtures for the `/ut/v1/youtube-cookies` endpoints: a client whose API keys map to an
admin or a normal user, and a server with an encryption key configured. No network."""

from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from ultimatetunes.app import create_app
from ultimatetunes.core.authn import Principal
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.services import Services, build_services
from ultimatetunes.db import Database, migrate
from ultimatetunes.errors import AuthenticationRequired, InvalidApiKey
from ultimatetunes.settings import Settings

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
ADMIN_KEY = "admin-key"
USER_KEY = "user-key"
ADMIN = Principal("0199d6a2-4c1e-7b3a-9f10-2a6c8e01f001", "ada", "admin")
USER = Principal("0199d6a2-4c1e-7b3a-9f10-2a6c8e01f002", "ned", "user")


class KeyAuth:
    """Maps the test API keys to principals; any other key is invalid, none is unauthenticated."""

    def authenticate_subsonic(
        self, params: Mapping[str, Sequence[str]], client_ip: str | None
    ) -> Principal:  # pragma: no cover - the ut endpoints use the key authenticator
        raise AuthenticationRequired("no")

    def authenticate_api_key(
        self, header_key: str | None, query_key: str | None, client_ip: str | None
    ) -> Principal:
        key = header_key or query_key
        if key is None:
            raise AuthenticationRequired("Provide an API key")
        if key == ADMIN_KEY:
            return ADMIN
        if key == USER_KEY:
            return USER
        raise InvalidApiKey("The API key is unknown or revoked")


@pytest.fixture
def cookies_key() -> str:
    return Fernet.generate_key().decode("ascii")


@pytest.fixture(autouse=True)
def _key_env(monkeypatch: pytest.MonkeyPatch, cookies_key: str) -> None:
    monkeypatch.setenv("UT_YTDLP_COOKIES_KEY", cookies_key)


def _add_user(db: Database, principal: Principal) -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO users (id, username, password_hash, role, created_at, updated_at)"
            " VALUES (?, ?, 'x', ?, '2026-10-01T00:00:00.000Z', '2026-10-01T00:00:00.000Z')",
            (principal.user_id, principal.username, principal.role),
        )


@pytest.fixture
def services(settings: Settings, clock: FakeClock) -> Iterator[Services]:
    conn = migrate.connect(settings.database_file)
    migrate.migrate(conn, CONTRACTS / "db" / "migrations", clock)
    conn.close()
    svc = build_services(settings, clock)
    svc.authenticator = KeyAuth()
    # The audit log references `users`: the actor must exist.
    _add_user(svc.db, ADMIN)
    _add_user(svc.db, USER)
    yield svc
    svc.db.close()


@pytest.fixture
def client(services: Services) -> Iterator[TestClient]:
    with TestClient(create_app(services=services)) as test_client:
        yield test_client
