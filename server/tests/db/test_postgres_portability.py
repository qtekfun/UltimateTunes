# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Migrations and the driver layer are portable: they also run on PostgreSQL (SPEC §3).

Runs only when UT_TEST_POSTGRES_URL points at a disposable database (CI contracts job,
`make contracts` locally). Each test works in a fresh schema that is dropped afterwards.
"""

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from ultimatetunes.core.clock import FakeClock
from ultimatetunes.db import Database, DatabaseError, IntegrityError, migrate
from ultimatetunes.db.driver import PostgresConnection, connect_postgres

CONTRACT_MIGRATIONS = Path(__file__).resolve().parents[3] / "contracts" / "db" / "migrations"
POSTGRES_URL = os.environ.get("UT_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(POSTGRES_URL is None, reason="UT_TEST_POSTGRES_URL not set"),
]


@pytest.fixture
def schema() -> Iterator[str]:
    assert POSTGRES_URL is not None
    name = f"ut_{uuid.uuid4().hex[:12]}"
    admin = connect_postgres(POSTGRES_URL)
    admin.execute(f'CREATE SCHEMA "{name}"')
    try:
        yield name
    finally:
        admin.execute(f'DROP SCHEMA "{name}" CASCADE')
        admin.close()


@pytest.fixture
def pg(schema: str) -> Iterator[PostgresConnection]:
    assert POSTGRES_URL is not None
    conn = connect_postgres(POSTGRES_URL)
    conn.execute(f'SET search_path TO "{schema}"')
    yield conn
    conn.close()


def test_contract_migrations_apply_on_postgres(pg: PostgresConnection) -> None:
    applied = migrate.migrate(pg, CONTRACT_MIGRATIONS, FakeClock())
    assert len(applied) == len(migrate.discover(CONTRACT_MIGRATIONS))
    assert migrate.pending(pg, CONTRACT_MIGRATIONS) == []
    assert pg.table_exists("tracks")
    assert not pg.table_exists("nope")


def test_failed_migration_is_rolled_back_on_postgres(
    pg: PostgresConnection, tmp_path: Path
) -> None:
    (tmp_path / "0001_ok.sql").write_text("CREATE TABLE a (id TEXT PRIMARY KEY);\n")
    (tmp_path / "0002_bad.sql").write_text("CREATE TABLE b (id TEXT);\nNOT SQL;\n")
    with pytest.raises(DatabaseError):
        migrate.migrate(pg, tmp_path)
    assert migrate.applied_versions(pg) == {1}
    assert not pg.table_exists("b")


def test_placeholders_literals_and_integrity_errors(pg: PostgresConnection) -> None:
    pg.execute("CREATE TABLE t (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
    pg.execute("INSERT INTO t (k, v) VALUES (?, '100% sure?')", ("a",))
    row = pg.execute("SELECT v FROM t WHERE k = ? AND v LIKE '%sure%'", ("a",)).fetchone()
    assert row == {"v": "100% sure?"}
    with pytest.raises(IntegrityError):
        pg.execute("INSERT INTO t (k, v) VALUES (?, ?)", ("a", "dup"))


def insert_then_fail(db: Database) -> None:
    with db.transaction() as conn:
        conn.execute("INSERT INTO t (k) VALUES (?)", ("x",))
        raise RuntimeError("roll back")


def test_database_transactions_on_postgres(schema: str) -> None:
    assert POSTGRES_URL is not None

    def opener() -> PostgresConnection:
        assert POSTGRES_URL is not None
        conn = connect_postgres(POSTGRES_URL)
        conn.execute(f'SET search_path TO "{schema}"')
        return conn

    db = Database(opener)
    try:
        with db.transaction() as conn:
            conn.execute("CREATE TABLE t (k TEXT PRIMARY KEY)")
        with pytest.raises(RuntimeError, match="roll back"):
            insert_then_fail(db)
        with db.read() as conn:
            assert conn.execute("SELECT COUNT(*) AS n FROM t").scalar() == 0
    finally:
        db.close()
