# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The `ultimatetunes` command and its roles."""

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from ultimatetunes import __version__, cli
from ultimatetunes.commands import CommandRegistry
from ultimatetunes.db import migrate
from ultimatetunes.settings import Settings


def test_migrate_role_applies_migrations(settings: Settings) -> None:
    (settings.migrations_dir / "0001_init.sql").write_text("CREATE TABLE a (id INTEGER);")
    assert cli.run_migrate(settings) == 0
    conn = migrate.connect(settings.database_file)
    assert migrate.applied_versions(conn) == {1}
    conn.close()


def test_api_role_runs_uvicorn_with_graceful_shutdown(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr("ultimatetunes.cli.uvicorn.run", lambda app, **kw: calls.append(kw))
    assert cli.run_api(settings) == 0
    assert calls[0]["port"] == 8044
    assert calls[0]["timeout_graceful_shutdown"] == settings.shutdown_timeout_s
    assert calls[0]["log_config"] is None


def test_main_dispatches_to_the_command_with_its_arguments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, migrations_dir: Path
) -> None:
    monkeypatch.setenv("UT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("UT_MIGRATIONS_DIR", str(migrations_dir))
    monkeypatch.setenv("UT_LOG_LEVEL", "WARNING")
    seen: list[tuple[Settings, list[str]]] = []

    def command(s: Settings, args: Sequence[str]) -> int:
        seen.append((s, list(args)))
        return 3

    registry = CommandRegistry()
    registry.add("echo", command, help="test")
    assert cli.main(["echo", "a", "--flag"], registry) == 3
    assert seen[0][0].data_dir == tmp_path / "data"
    assert seen[0][1] == ["a", "--flag"]


def test_main_builds_the_registry_of_every_area(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Settings] = []

    def migrate_stub(s: Settings) -> int:
        calls.append(s)
        return 0

    monkeypatch.setattr(cli, "run_migrate", migrate_stub)
    monkeypatch.setenv("UT_LOG_LEVEL", "WARNING")
    assert cli.main(["migrate"]) == 0
    assert len(calls) == 1


def test_main_rejects_unknown_commands_and_extra_arguments() -> None:
    with pytest.raises(SystemExit):
        cli.main(["nope"])
    with pytest.raises(SystemExit, match="unexpected arguments: x"):
        cli.main(["migrate", "x"])


def test_settings_default_database_lives_in_data_dir(tmp_path: Path) -> None:
    assert Settings(data_dir=tmp_path).database_file == tmp_path / "ultimatetunes.db"
    assert Settings(database_path=tmp_path / "x.db").database_file == tmp_path / "x.db"


def test_python_dash_m_prints_the_version() -> None:
    out = subprocess.run(
        [sys.executable, "-m", "ultimatetunes", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip() == __version__


def test_secrets_are_read_from_docker_secret_files(tmp_path: Path) -> None:
    """compose.yaml mounts the worker token as /run/secrets/ut_worker_token."""
    (tmp_path / "ut_worker_token").write_text("token-from-file\n")
    settings = Settings(_secrets_dir=tmp_path)
    assert settings.worker_token is not None
    assert settings.worker_token.get_secret_value() == "token-from-file"
