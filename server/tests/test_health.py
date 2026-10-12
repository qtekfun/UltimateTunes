# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Liveness never depends on anything; readiness checks database, schema and storage."""

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ultimatetunes.app import create_app
from ultimatetunes.db import migrate
from ultimatetunes.settings import Settings


def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


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
