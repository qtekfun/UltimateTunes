# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The real app for the contract tests (PLAN T19), built once at import time.

schemathesis needs the app when it collects the tests, so this module builds it eagerly:

- a temporary data, music and staging tree, every contract migration applied;
- the invented library of `tests/library/harness.py` on disk, scanned;
- the fake catalog and fake downloader (`UT_FAKE_YOUTUBE`): nothing reaches YouTube;
- the real authenticator (PLAN T04) with one user and one API key created through
  `AuthService`, as an admin would, and limits high enough that generated traffic is never
  throttled (a 429 is valid but would hide the endpoint behind it);
- a worker token for the internal worker API.

The app's lifespan runs once per session (`conftest.py`); schemathesis drives it through
`SessionLifespan`, which answers `lifespan` itself so the database is not closed after the
first generated call.
"""

import tempfile
from pathlib import Path

from argon2 import PasswordHasher, Type
from pydantic import SecretStr
from starlette.types import ASGIApp, Receive, Scope, Send

from tests.conftest import CONTRACTS
from tests.library.harness import seed_files
from ultimatetunes.app import create_app
from ultimatetunes.auth.passwords import Passwords
from ultimatetunes.auth.service import AuthService
from ultimatetunes.auth.settings import AuthSettings
from ultimatetunes.core.services import Services, build_services
from ultimatetunes.db import migrate
from ultimatetunes.library.scan import LibraryScanner
from ultimatetunes.settings import Settings

OPENAPI = CONTRACTS / "openapi"
TOKEN = "contract-test-worker-token"
USERNAME = "contract"
PASSWORD = "contract test passphrase"
# Generated traffic is fast and full of bad credentials: no throttling, no lockout.
_UNLIMITED = 1_000_000


def _settings(root: Path) -> Settings:
    for name in ("data", "music", "staging"):
        (root / name).mkdir()
    return Settings(
        data_dir=root / "data",
        music_dir=root / "music",
        staging_dir=root / "staging",
        migrations_dir=CONTRACTS / "db" / "migrations",
        worker_token=SecretStr(TOKEN),
        fake_youtube=True,
    )


def _auth(services: Services) -> AuthService:
    limits = AuthSettings(
        bootstrap_admin_username=None,
        bootstrap_admin_password=None,
        auth_max_failures_per_ip=_UNLIMITED,
        auth_max_failures_per_user=_UNLIMITED,
        auth_key_rate_per_s=_UNLIMITED,
        auth_key_burst=_UNLIMITED,
        auth_login_rate_per_s=_UNLIMITED,
        auth_login_burst=_UNLIMITED,
    )
    # Argon2id with the smallest parameters: the same code path, milliseconds per hash.
    fast = Passwords(PasswordHasher(time_cost=1, memory_cost=8, parallelism=1, type=Type.ID))
    return AuthService(services.db, services.clock, services.rate_limiter, limits, fast)


def _build() -> tuple[tempfile.TemporaryDirectory[str], Services, str, str]:
    root = tempfile.TemporaryDirectory(prefix="ut-contract-")
    settings = _settings(Path(root.name))
    conn = migrate.connect(settings.database_file)
    try:
        migrate.migrate(conn, settings.migrations_dir)
    finally:
        conn.close()
    services = build_services(settings)
    auth = _auth(services)
    services.authenticator = auth
    user = auth.create_user(USERNAME, PASSWORD, "user", actor=None)
    key = auth.create_key(user.id, "schemathesis", actor=None).secret
    seed_files(settings.music_dir)
    LibraryScanner(services.db, services.library, services.clock).scan()
    return root, services, user.id, key


_ROOT, SERVICES, USER_ID, API_KEY = _build()
APP = create_app(services=SERVICES)


class SessionLifespan:
    """Forwards every HTTP call to the app and answers `lifespan` without forwarding it."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "lifespan":
            await self.app(scope, receive, send)
            return
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return


def library_ids() -> dict[str, str]:
    """Title → track id, artist name → artist id, album name → album id."""
    with SERVICES.db.read() as conn:
        rows = conn.execute(
            "SELECT title AS k, id FROM tracks UNION ALL SELECT name AS k, id FROM artists"
            " UNION ALL SELECT name AS k, id FROM albums"
        ).fetchall()
    return {str(r["k"]): str(r["id"]) for r in rows}
