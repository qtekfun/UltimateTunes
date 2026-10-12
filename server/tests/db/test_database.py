# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Connection management on SQLite: one serialized writer, pooled readers, lazy opening."""

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from ultimatetunes.db import Database, DatabaseError, IntegrityError
from ultimatetunes.db.driver import connect_sqlite, to_format_style


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database.sqlite(tmp_path / "data" / "ut.db", readers=2)
    with database.transaction() as conn:
        conn.execute("CREATE TABLE t (k TEXT NOT NULL PRIMARY KEY, n INTEGER NOT NULL)")
    yield database
    database.close()


def test_nothing_is_opened_until_first_use(tmp_path: Path) -> None:
    Database.sqlite(tmp_path / "data" / "ut.db")
    assert not (tmp_path / "data").exists()


def test_transaction_commits_and_readers_see_it(db: Database) -> None:
    with db.transaction() as conn:
        conn.execute("INSERT INTO t (k, n) VALUES (?, ?)", ("a", 1))
    with db.read() as conn:
        assert conn.execute("SELECT n FROM t WHERE k = ?", ("a",)).scalar() == 1
        assert conn.execute("SELECT n FROM t WHERE k = ?", ("zz",)).scalar() is None
    db.close()


def insert_then_fail(db: Database) -> None:
    with db.transaction() as conn:
        conn.execute("INSERT INTO t (k, n) VALUES (?, ?)", ("a", 1))
        raise ValueError("boom")


def test_transaction_rolls_back_on_error(db: Database) -> None:
    with pytest.raises(ValueError, match="boom"):
        insert_then_fail(db)
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM t").scalar() == 0


def test_integrity_and_other_errors_are_translated(db: Database) -> None:
    with db.transaction() as conn:
        conn.execute("INSERT INTO t (k, n) VALUES (?, ?)", ("a", 1))
    with pytest.raises(IntegrityError), db.transaction() as conn:
        conn.execute("INSERT INTO t (k, n) VALUES (?, ?)", ("a", 2))
    with pytest.raises(DatabaseError), db.read() as conn:
        conn.execute("SELECT nope FROM t")


def test_nested_transactions_are_refused(tmp_path: Path) -> None:
    conn = connect_sqlite(tmp_path / "x.db")
    try:
        with pytest.raises(RuntimeError, match="nested"), conn.transaction(), conn.transaction():
            pass  # pragma: no cover - never reached
    finally:
        conn.close()


def test_writes_are_serialized(db: Database) -> None:
    def bump(i: int) -> None:
        with db.transaction() as conn:
            conn.execute("INSERT INTO t (k, n) VALUES (?, ?)", (f"k{i}", i))

    threads = [threading.Thread(target=bump, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM t").scalar() == 20


def test_readers_are_reused(db: Database) -> None:
    with db.read() as first:
        pass
    with db.read() as second:
        assert second is first


def test_closed_database_refuses_new_connections(db: Database) -> None:
    db.close()
    with pytest.raises(RuntimeError, match="closed"), db.read():
        pass  # pragma: no cover - never reached


def test_reader_count_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="reader"):
        Database.sqlite(tmp_path / "x.db", readers=0)


def test_read_only_connection_never_creates_the_file(tmp_path: Path) -> None:
    with pytest.raises(DatabaseError):
        connect_sqlite(tmp_path / "missing.db", read_only=True)
    assert not (tmp_path / "missing.db").exists()


def test_wal_and_foreign_keys_are_on(tmp_path: Path) -> None:
    conn = connect_sqlite(tmp_path / "x.db")
    assert conn.execute("PRAGMA journal_mode").scalar() == "wal"
    assert conn.execute("PRAGMA foreign_keys").scalar() == 1
    conn.close()


@pytest.mark.parametrize(
    ("portable", "psycopg"),
    [
        ("SELECT * FROM t WHERE k = ? AND n = ?", "SELECT * FROM t WHERE k = %s AND n = %s"),
        ("SELECT '?' FROM t WHERE k = ?", "SELECT '?' FROM t WHERE k = %s"),
        ("SELECT 'it''s ?' WHERE v LIKE '%x%'", "SELECT 'it''s ?' WHERE v LIKE '%%x%%'"),
    ],
)
def test_placeholders_become_format_style(portable: str, psycopg: str) -> None:
    assert to_format_style(portable) == psycopg
