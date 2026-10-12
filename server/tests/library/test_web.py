# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The library's app hook: the streaming seam default and the startup scan."""

import pytest
from fastapi.testclient import TestClient

from tests.conftest import CONTRACTS
from tests.library.harness import seed_files
from ultimatetunes.app import create_app
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.services import build_services
from ultimatetunes.db import Database, migrate
from ultimatetunes.library.stream import NotStreamingYet
from ultimatetunes.library.web import library_settings
from ultimatetunes.settings import Settings


@pytest.fixture
def migrated(settings: Settings) -> Settings:
    conn = migrate.connect(settings.database_file)
    migrate.migrate(conn, CONTRACTS / "db" / "migrations", FakeClock())
    conn.close()
    return settings


@pytest.mark.parametrize("enabled", [True, False])
def test_startup_scan(migrated: Settings, monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    monkeypatch.setenv("UT_LIBRARY_SCAN_ON_START", str(enabled).lower())
    library_settings.cache_clear()
    seed_files(migrated.music_dir)
    services = build_services(migrated, FakeClock())
    try:
        app = create_app(services=services)
        assert isinstance(app.state.pending_streams, NotStreamingYet)
        with TestClient(app):
            if enabled:
                app.state.library_scan.join(10)
        db = Database.sqlite(migrated.database_file)
        with db.read() as conn:
            count = conn.execute("SELECT COUNT(*) FROM tracks").scalar()
        db.close()
    finally:
        library_settings.cache_clear()
    assert count == (3 if enabled else 0)


def test_startup_scan_failure_is_logged(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # No migrations: the scan's first query fails, the api still starts and stops.
    monkeypatch.setenv("UT_LIBRARY_SCAN_ON_START", "true")
    library_settings.cache_clear()
    seed_files(settings.music_dir)
    app = create_app(services=build_services(settings, FakeClock()))
    try:
        with TestClient(app) as client:
            app.state.library_scan.join(10)
            assert client.get("/healthz").status_code == 200
    finally:
        library_settings.cache_clear()
    assert "library scan" in caplog.text
