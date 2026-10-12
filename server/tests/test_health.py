# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Liveness never depends on anything; readiness checks database, schema and storage."""

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ultimatetunes.app import create_app
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.services import build_services
from ultimatetunes.db import migrate
from ultimatetunes.health import READYZ_CACHE_S
from ultimatetunes.settings import Settings

LOCAL = ("127.0.0.1", 50000)
LAN = ("192.168.1.20", 50000)
PUBLIC = ("203.0.113.7", 50000)


def client(settings: Settings, peer: tuple[str, int] = LOCAL) -> TestClient:
    return TestClient(create_app(settings), client=peer)


def migrated(settings: Settings) -> Settings:
    conn = migrate.connect(settings.database_file)
    migrate.migrate(conn, settings.migrations_dir)
    conn.close()
    return settings


def test_healthz_answers_without_dependencies(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "missing", migrations_dir=tmp_path / "missing")
    response = client(settings).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_ok_when_everything_is_ready(settings: Settings) -> None:
    response = client(migrated(settings)).get("/readyz")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"database": "ok", "music": "ok", "staging": "ok"},
    }


def test_readyz_fails_without_database(settings: Settings) -> None:
    response = client(settings).get("/readyz")
    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "missing"


def test_readyz_fails_with_pending_migrations(settings: Settings) -> None:
    migrated(settings)
    (settings.migrations_dir / "0001_init.sql").write_text("CREATE TABLE a (id INTEGER);")
    response = client(settings).get("/readyz")
    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "migrations pending"


def test_readyz_reports_database_errors(settings: Settings) -> None:
    migrated(settings)
    shutil.rmtree(settings.migrations_dir)
    response = client(settings).get("/readyz")
    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "error"


@pytest.mark.parametrize("which", ["music", "staging"])
def test_readyz_fails_when_storage_is_not_writable(settings: Settings, which: str) -> None:
    migrated(settings)
    directory: Path = getattr(settings, f"{which}_dir")
    shutil.rmtree(directory)  # a missing mount is as unwritable as a read-only one
    response = client(settings).get("/readyz")
    assert response.status_code == 503
    assert response.json()["checks"][which] == "not writable"


def test_docs_and_openapi_are_not_exposed(settings: Settings) -> None:
    c = client(settings)
    assert c.get("/docs").status_code == 404
    assert c.get("/openapi.json").status_code == 404


def test_readyz_detail_only_for_local_and_allowlisted_callers(settings: Settings) -> None:
    migrated(settings)
    # Inside the admin allowlist (LAN by default): the detail.
    assert "checks" in client(settings, LAN).get("/readyz").json()
    # From the Internet: only the status.
    public = client(settings, PUBLIC).get("/readyz")
    assert public.status_code == 200
    assert public.json() == {"status": "ok"}
    # Through a proxy nobody declared (every caller looks local): only the status.
    proxied = client(settings, LOCAL).get("/readyz", headers={"X-Forwarded-For": "203.0.113.9"})
    assert proxied.json() == {"status": "ok"}


def test_readyz_failure_keeps_its_status_without_detail(settings: Settings) -> None:
    response = client(settings, PUBLIC).get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_readyz_detail_through_a_trusted_proxy(settings: Settings) -> None:
    migrated(settings)
    behind = settings.model_copy(update={"trusted_proxies": "172.16.0.0/12"})
    proxy = ("172.18.0.1", 40000)
    from_lan = client(behind, proxy).get("/readyz", headers={"X-Forwarded-For": "192.168.1.5"})
    assert "checks" in from_lan.json()
    from_outside = client(behind, proxy).get("/readyz", headers={"X-Forwarded-For": "203.0.113.9"})
    assert from_outside.json() == {"status": "ok"}


def test_readyz_detail_never_goes_to_the_worker_network(settings: Settings) -> None:
    migrated(settings)
    walled = settings.model_copy(update={"worker_networks": "172.30.44.0/24"})
    assert client(walled, ("172.30.44.3", 1)).get("/readyz").json() == {"status": "ok"}
    assert "checks" in client(walled, LOCAL).get("/readyz").json()


def test_readyz_caches_its_checks_for_a_few_seconds(settings: Settings) -> None:
    """Audit L3: a flood of probes does not reopen the database on every request."""
    clock = FakeClock()
    app = create_app(services=build_services(settings, clock))
    probe = TestClient(app, client=LOCAL)
    assert probe.get("/readyz").json()["checks"]["database"] == "missing"
    migrated(settings)
    assert probe.get("/readyz").status_code == 503
    clock.advance(READYZ_CACHE_S - 0.1)
    assert probe.get("/readyz").status_code == 503
    clock.advance(0.1)
    assert probe.get("/readyz").status_code == 200
