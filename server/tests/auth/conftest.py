# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixtures of the auth tests: a migrated database, a fast Argon2id hasher, users and keys."""

import secrets
from dataclasses import dataclass
from pathlib import Path

import pytest
from argon2 import PasswordHasher, Type
from cryptography.fernet import Fernet
from pydantic import SecretStr

from tests.conftest import CONTRACTS
from ultimatetunes.auth.passwords import Passwords
from ultimatetunes.auth.service import AuthService
from ultimatetunes.auth.settings import AuthSettings
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.ratelimit import SqliteRateLimiter
from ultimatetunes.db import Database, migrate
from ultimatetunes.settings import Settings

# Made at runtime (12+ characters for the policy): no credential-looking literal in the tests.
ADMIN_PASSWORD = secrets.token_urlsafe(16)
USER_PASSWORD = secrets.token_urlsafe(16)
# A fresh Fernet key per test run, so 2FA secrets can be sealed; never a literal in the source.
TOTP_KEY = SecretStr(Fernet.generate_key().decode("ascii"))
IP = "192.0.2.10"


def fast_passwords() -> Passwords:
    """Argon2id with the smallest parameters: same code path, milliseconds per hash."""
    return Passwords(PasswordHasher(time_cost=1, memory_cost=8, parallelism=1, type=Type.ID))


def migrate_file(path: Path) -> None:
    conn = migrate.connect(path)
    migrate.migrate(conn, CONTRACTS / "db" / "migrations", FakeClock())
    conn.close()


@pytest.fixture
def auth_settings() -> AuthSettings:
    return AuthSettings(
        bootstrap_admin_username=None,
        bootstrap_admin_password=None,
        auth_max_failures_per_ip=3,
        auth_max_failures_per_user=2,
        auth_lockout_s=60,
        auth_key_rate_per_s=1.0,
        auth_key_burst=50.0,
        auth_login_rate_per_s=1.0,
        auth_login_burst=50.0,
        totp_encryption_key=TOTP_KEY,
    )


@pytest.fixture
def service(db: Database, clock: FakeClock, auth_settings: AuthSettings) -> AuthService:
    return AuthService(db, clock, SqliteRateLimiter(db, clock), auth_settings, fast_passwords())


@dataclass(frozen=True)
class Account:
    user_id: str
    username: str
    password: str
    key: str
    key_id: str


def make_account(service: AuthService, username: str, password: str, role: str) -> Account:
    user = service.create_user(username, password, role, actor=None)
    created = service.create_key(user.id, f"{username} phone", actor=None)
    return Account(user.id, user.username, password, created.secret, created.key.id)


@pytest.fixture
def admin(service: AuthService) -> Account:
    return make_account(service, "Alice", ADMIN_PASSWORD, "admin")


@pytest.fixture
def user(service: AuthService) -> Account:
    return make_account(service, "bob", USER_PASSWORD, "user")


@pytest.fixture
def migrated_settings(settings: Settings) -> Settings:
    migrate_file(settings.database_file)
    return settings
