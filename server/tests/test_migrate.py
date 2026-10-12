# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The migrator applies portable SQL files in order, once, each in its own transaction."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from ultimatetunes.core.clock import FakeClock
from ultimatetunes.db import DatabaseError, migrate
from ultimatetunes.db.driver import SqliteConnection

CONTRACT_MIGRATIONS = Path(__file__).resolve().parents[2] / "contracts" / "db" / "migrations"


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[SqliteConnection]:
    connection = migrate.connect(tmp_path / "db" / "ut.db")
    yield connection
    connection.close()


def write(directory: Path, name: str, sql: str) -> None:
    (directory / name).write_text(sql, encoding="utf-8")


def test_empty_directory_applies_nothing(conn: SqliteConnection, migrations_dir: Path) -> None:
    assert migrate.migrate(conn, migrations_dir) == []
    assert migrate.applied_versions(conn) == set()


def test_applies_in_order_and_only_once(conn: SqliteConnection, migrations_dir: Path) -> None:
    write(migrations_dir, "0002_more.sql", "-- second\nALTER TABLE a ADD COLUMN b TEXT;\n")
    write(migrations_dir, "0001_init.sql", "CREATE TABLE a (id INTEGER PRIMARY KEY);\n")

    applied = migrate.migrate(conn, migrations_dir, FakeClock())

    assert [m.version for m in applied] == [1, 2]
    assert migrate.migrate(conn, migrations_dir) == []
    assert migrate.applied_versions(conn) == {1, 2}
    conn.execute("INSERT INTO a (id, b) VALUES (1, 'x')")
    stamps = conn.execute("SELECT applied_at FROM schema_migrations").fetchall()
    assert {r["applied_at"] for r in stamps} == {"2026-10-12T08:00:00.000Z"}


def test_failed_migration_is_rolled_back(conn: SqliteConnection, migrations_dir: Path) -> None:
    write(migrations_dir, "0001_init.sql", "CREATE TABLE a (id INTEGER);\n")
    write(migrations_dir, "0002_bad.sql", "CREATE TABLE b (id INTEGER);\nNOT SQL;\n")

    with pytest.raises(DatabaseError):
        migrate.migrate(conn, migrations_dir)

    assert migrate.applied_versions(conn) == {1}
    assert not conn.table_exists("b")


def test_rejects_bad_names_and_duplicates(migrations_dir: Path) -> None:
    write(migrations_dir, "init.sql", "SELECT 1;")
    with pytest.raises(ValueError, match="bad migration file name"):
        migrate.discover(migrations_dir)
    (migrations_dir / "init.sql").unlink()
    write(migrations_dir, "0001_a.sql", "SELECT 1;")
    write(migrations_dir, "0001_b.sql", "SELECT 1;")
    with pytest.raises(ValueError, match="share a version"):
        migrate.discover(migrations_dir)


def test_missing_directory_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        migrate.discover(tmp_path / "nope")


def test_split_statements_drops_comments_and_blanks() -> None:
    sql = "-- header\nCREATE TABLE a (x INTEGER);\n\n  -- note\nCREATE TABLE b (y TEXT);\n"
    assert migrate.split_statements(sql) == [
        "CREATE TABLE a (x INTEGER)",
        "CREATE TABLE b (y TEXT)",
    ]


def test_split_statements_keeps_semicolons_inside_a_line() -> None:
    sql = "CREATE TABLE a (sep TEXT NOT NULL DEFAULT ';');\nCREATE TABLE b (x INTEGER);  \n"
    assert migrate.split_statements(sql) == [
        "CREATE TABLE a (sep TEXT NOT NULL DEFAULT ';')",
        "CREATE TABLE b (x INTEGER)",
    ]


def test_contract_migrations_apply_on_sqlite(conn: SqliteConnection) -> None:
    """Every migration in contracts/ applies on an empty SQLite database (CI contracts job)."""
    applied = migrate.migrate(conn, CONTRACT_MIGRATIONS)
    assert migrate.pending(conn, CONTRACT_MIGRATIONS) == []
    assert len(applied) == len(migrate.discover(CONTRACT_MIGRATIONS)) >= 1
    assert conn.table_exists("cache_entries")


def test_contract_migrations_follow_the_statement_rules() -> None:
    """contracts/db/README.md: statements end with `;` at the end of a line, nothing else does,
    comments sit on their own lines. A `;` that does not end a line would be a split hazard."""
    for migration in migrate.discover(CONTRACT_MIGRATIONS):
        for number, line in enumerate(migration.sql.splitlines(), start=1):
            code = line.strip()
            where = f"{migration.name}:{number}"
            if code.startswith("--") or not code:
                continue
            assert "--" not in code, f"{where}: trailing comment"
            assert "/*" not in code, f"{where}: block comment"
            assert ";" not in code.rstrip(";"), f"{where}: semicolon inside a line"
