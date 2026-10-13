# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared fixtures: settings pointing at a temporary data, music and staging tree."""

import ipaddress
import socket
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.security_events import events  # noqa: F401 - a fixture for every test
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


def _is_loopback(host: object) -> bool:
    if host == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(str(host).split("%", 1)[0])
    except ValueError:
        return False  # any other hostname would need DNS: not allowed in tests
    mapped = getattr(ip, "ipv4_mapped", None)
    return bool((mapped or ip).is_loopback)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fails any test that opens a connection outside this machine (CLAUDE.md: no real network
    in tests). Loopback stays allowed (local fake servers); PostgreSQL goes through libpq."""
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def check(sock: socket.socket, address: object) -> None:
        if sock.family not in (socket.AF_INET, socket.AF_INET6):
            return
        host = address[0] if isinstance(address, tuple) else address
        if not _is_loopback(host):
            raise OSError(f"test tried to reach the network: {address!r}")

    def connect(self: socket.socket, address: object) -> None:
        check(self, address)
        real_connect(self, address)  # type: ignore[arg-type]

    def connect_ex(self: socket.socket, address: object) -> int:
        check(self, address)
        return real_connect_ex(self, address)  # type: ignore[arg-type]

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
