# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared fixtures: settings pointing at a temporary data, music and staging tree."""

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
