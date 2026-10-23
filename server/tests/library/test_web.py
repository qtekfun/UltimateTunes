# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The library's app hook: the streaming seam default, the startup scan and the size limit
check."""

import anyio
import pytest
from fastapi.testclient import TestClient

from tests.conftest import CONTRACTS
from tests.library.harness import seed_files
from ultimatetunes.app import create_app
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.services import build_services
from ultimatetunes.db import Database, migrate
from ultimatetunes.library.evict import Evictor
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
        assert not isinstance(app.state.pending_streams, NotStreamingYet)
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


@pytest.mark.parametrize(("interval", "runs"), [("600", True), ("0", False)])
def test_size_limit_check_runs_with_the_app(
    migrated: Settings, monkeypatch: pytest.MonkeyPatch, interval: str, runs: bool
) -> None:
    monkeypatch.setenv("UT_LIBRARY_SCAN_ON_START", "false")
    monkeypatch.setenv("UT_LIBRARY_EVICT_INTERVAL_S", interval)
    library_settings.cache_clear()
    seen: list[str] = []

    async def run_forever(self: Evictor, interval_s: float) -> None:
        seen.append(f"start {interval_s:g}")
        try:
            await anyio.sleep_forever()
        finally:
            seen.append("stop")

    monkeypatch.setattr(Evictor, "run_forever", run_forever)
    try:
        app = create_app(services=build_services(migrated, FakeClock()))
        with TestClient(app) as client:
            assert client.get("/healthz").status_code == 200
    finally:
        library_settings.cache_clear()
    assert seen == (["start 600", "stop"] if runs else [])
