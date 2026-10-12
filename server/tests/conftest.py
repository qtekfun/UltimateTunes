# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared fixtures: settings pointing at a temporary data, music and staging tree."""

import socket
from collections.abc import Iterator
from pathlib import Path

import pytest

from ultimatetunes.core.clock import FakeClock
from ultimatetunes.db import Database, migrate
from ultimatetunes.settings import Settings


@pytest.fixture
def migrations_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "migrations"
    directory.mkdir()
    return directory


@pytest.fixture
def settings(tmp_path: Path, migrations_dir: Path) -> Settings:
    for name in ("data", "music", "staging"):
        (tmp_path / name).mkdir()
    return Settings(
        data_dir=tmp_path / "data",
        music_dir=tmp_path / "music",
        staging_dir=tmp_path / "staging",
        migrations_dir=migrations_dir,
        # Tests never reach YouTube Music (CLAUDE.md); only the nightly/server canary does.
        fake_youtube=True,
    )


CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def db(tmp_path: Path, clock: FakeClock) -> Iterator[Database]:
    """A database with every contract migration applied."""
    path = tmp_path / "data" / "ut.db"
    conn = migrate.connect(path)
    migrate.migrate(conn, CONTRACTS / "db" / "migrations", clock)
    conn.close()
    database = Database.sqlite(path)
    yield database
    database.close()


_LOOPBACK = ("127.", "::1", "localhost")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fails any test that opens a connection outside this machine (CLAUDE.md: no real network
    in tests). Loopback stays allowed for the disposable PostgreSQL of the contract tests."""
    real_connect = socket.socket.connect

    def guarded(self: socket.socket, address: object) -> object:
        host = address[0] if isinstance(address, tuple) else str(address)
        if not str(host).startswith(_LOOPBACK) and self.family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError(f"test tried to reach the network: {address!r}")
        return real_connect(self, address)  # type: ignore[arg-type]

    monkeypatch.setattr(socket.socket, "connect", guarded)
