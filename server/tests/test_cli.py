# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The `ultimatetunes` command and its roles."""

import signal
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from types import FrameType
from typing import Any

import pytest

from ultimatetunes import __version__, cli
from ultimatetunes.db import migrate
from ultimatetunes.settings import Settings

Handler = Callable[[int, FrameType | None], None]


def test_migrate_role_applies_migrations(settings: Settings) -> None:
    (settings.migrations_dir / "0001_init.sql").write_text("CREATE TABLE a (id INTEGER);")
    assert cli.run_migrate(settings) == 0
    conn = migrate.connect(settings.database_file)
    assert migrate.applied_versions(conn) == {1}
    conn.close()


def test_worker_stops_on_sigterm(settings: Settings) -> None:
    handlers: dict[int, Handler] = {}

    def install(signum: int, handler: Handler) -> None:
        handlers[signum] = handler

    stop = threading.Event()
    thread = threading.Thread(target=cli.run_worker, args=(settings, stop, install))
    thread.start()
    while signal.SIGTERM not in handlers:
        thread.join(timeout=0.01)
    handlers[signal.SIGTERM](signal.SIGTERM, None)
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert signal.SIGINT in handlers


def test_api_role_runs_uvicorn_with_graceful_shutdown(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr("ultimatetunes.cli.uvicorn.run", lambda app, **kw: calls.append(kw))
    assert cli.run_api(settings) == 0
    assert calls[0]["port"] == 8044
    assert calls[0]["timeout_graceful_shutdown"] == settings.shutdown_timeout_s
    assert calls[0]["log_config"] is None


def test_main_dispatches_to_the_role(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, migrations_dir: Path
) -> None:
    monkeypatch.setenv("UT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("UT_MIGRATIONS_DIR", str(migrations_dir))
    monkeypatch.setenv("UT_LOG_LEVEL", "WARNING")
    seen: list[Settings] = []

    def role(s: Settings) -> int:
        seen.append(s)
        return 0

    monkeypatch.setitem(cli.ROLES, "migrate", role)
    assert cli.main(["migrate"]) == 0
    assert seen[0].data_dir == tmp_path / "data"


def test_main_rejects_unknown_roles() -> None:
    with pytest.raises(SystemExit):
        cli.main(["nope"])


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
