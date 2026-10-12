# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A small driver abstraction over SQLite (stdlib, ships in v1) and PostgreSQL (psycopg).

Everything above this module (migrator, repositories, SQLite-backed interfaces) talks to a
`Connection` and writes **portable SQL** with `?` placeholders (contracts/db/README.md). The
SQLite-only details (pragmas, WAL, `sqlite_master`) live here and nowhere else. PostgreSQL is
dev-only for now: CI applies the migrations on it, and PLAN T25 makes it a runtime option.
"""

import re
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    import psycopg

Dialect = Literal["sqlite", "postgresql"]
Row = Mapping[str, object]
Params = Sequence[object]

# How long a SQLite connection waits for the write lock before failing.
SQLITE_BUSY_TIMEOUT_MS = 5000

# `PRAGMA optimize` checking every table, not only the ones this connection used, and running
# ANALYZE (bit 0x02) where statistics are missing or stale. SQLite >= 3.46 (the image ships
# 3.46); older versions ignore the 0x10000 bit. Without statistics the planner picks
# low-selectivity indexes (e.g. `ix_tracks_status`) and browse queries get O(albums x tracks)
# (issue #54).
SQLITE_OPTIMIZE = "PRAGMA optimize=0x10002"


class DatabaseError(Exception):
    """Any driver error, translated so callers never import a driver module."""


class IntegrityError(DatabaseError):
    """A constraint (unique, foreign key, check, not null) refused the statement."""


class Result:
    """Rows of one statement, already materialized as dicts keyed by column name."""

    def __init__(self, rows: list[dict[str, object]], rowcount: int) -> None:
        self._rows = rows
        self.rowcount = rowcount

    def fetchone(self) -> Row | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[Row]:
        return list(self._rows)

    def scalar(self) -> object:
        """First column of the first row, or None when there is no row."""
        row = self.fetchone()
        return None if row is None else next(iter(row.values()))


class Connection(Protocol):
    """One database connection. Not thread-safe: `Database` hands them out."""

    dialect: Dialect

    def execute(self, sql: str, params: Params = ()) -> Result: ...

    def transaction(self) -> AbstractContextManager[None]:
        """Commits on success, rolls back on any exception. Not reentrant."""
        ...

    def table_exists(self, name: str) -> bool: ...

    def optimize(self) -> None:
        """Refreshes the query planner statistics of the tables that need it (SQLite
        `PRAGMA optimize`, PostgreSQL `ANALYZE`). Writes statistics: writer connections only."""
        ...

    def reload_statistics(self) -> None:
        """Makes this connection use statistics another connection refreshed (SQLite caches
        them per connection; a no-op on PostgreSQL)."""
        ...

    def close(self) -> None: ...


def _rows(cursor: sqlite3.Cursor) -> list[dict[str, object]]:
    if cursor.description is None:
        return []
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


class SqliteConnection:
    """SQLite in autocommit mode; `transaction()` opens `BEGIN IMMEDIATE` (one writer)."""

    dialect: Dialect = "sqlite"

    def __init__(self, raw: sqlite3.Connection) -> None:
        self.raw = raw
        self._in_tx = False

    def execute(self, sql: str, params: Params = ()) -> Result:
        try:
            cursor = self.raw.execute(sql, tuple(params))
            rows = _rows(cursor)
        except sqlite3.IntegrityError as exc:
            raise IntegrityError(str(exc)) from exc
        except sqlite3.Error as exc:
            raise DatabaseError(str(exc)) from exc
        return Result(rows, cursor.rowcount)

    @contextmanager
    def _tx(self) -> Iterator[None]:
        if self._in_tx:
            raise RuntimeError("nested transactions are not supported")
        self.execute("BEGIN IMMEDIATE")
        self._in_tx = True
        try:
            yield
            self.execute("COMMIT")
        except BaseException:
            if self.raw.in_transaction:
                self.raw.execute("ROLLBACK")
            raise
        finally:
            self._in_tx = False

    def transaction(self) -> AbstractContextManager[None]:
        return self._tx()

    def table_exists(self, name: str) -> bool:
        found = self.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone()
        return found is not None

    def optimize(self) -> None:
        self.execute(SQLITE_OPTIMIZE)

    def reload_statistics(self) -> None:
        # Documented way to make a connection re-read sqlite_stat1 written by another one.
        self.execute("ANALYZE sqlite_schema")

    def close(self) -> None:
        self.raw.close()


def connect_sqlite(path: Path, *, read_only: bool = False) -> SqliteConnection:
    """Opens a SQLite database: WAL, foreign keys on, a busy timeout. Read-only connections
    never create the file (used by `/readyz`)."""
    if not read_only:
        path.parent.mkdir(parents=True, exist_ok=True)
    target = f"file:{path}?mode=ro" if read_only else str(path)
    try:
        raw = sqlite3.connect(target, uri=read_only, isolation_level=None, check_same_thread=False)
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc
    try:
        if not read_only:
            raw.execute("PRAGMA journal_mode=WAL")
        raw.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        raw.execute("PRAGMA foreign_keys=ON")
    except sqlite3.Error as exc:
        raw.close()
        raise DatabaseError(str(exc)) from exc
    return SqliteConnection(raw)


# A string literal, or a `?` placeholder outside one.
_TOKEN = re.compile(r"'(?:[^']|'')*'|\?")


def to_format_style(sql: str) -> str:
    """Rewrites portable `?` placeholders as psycopg's `%s` (not inside string literals) and
    doubles every `%`, which psycopg would otherwise read as a placeholder."""
    escaped = sql.replace("%", "%%")
    return _TOKEN.sub(lambda m: "%s" if m.group(0) == "?" else m.group(0), escaped)


class PostgresConnection:
    """psycopg 3 in autocommit mode; `transaction()` maps to `conn.transaction()`."""

    dialect: Dialect = "postgresql"

    def __init__(self, raw: "psycopg.Connection[dict[str, object]]") -> None:
        self.raw = raw

    def execute(self, sql: str, params: Params = ()) -> Result:
        import psycopg  # noqa: PLC0415 - dev-only driver until PLAN T25

        try:
            cursor = self.raw.execute(to_format_style(sql).encode(), tuple(params))
            rows = cursor.fetchall() if cursor.description is not None else []
        except psycopg.IntegrityError as exc:
            raise IntegrityError(str(exc)) from exc
        except psycopg.Error as exc:
            raise DatabaseError(str(exc)) from exc
        return Result([dict(r) for r in rows], cursor.rowcount)

    @contextmanager
    def _tx(self) -> Iterator[None]:
        with self.raw.transaction():
            yield

    def transaction(self) -> AbstractContextManager[None]:
        return self._tx()

    def table_exists(self, name: str) -> bool:
        found = self.execute(
            "SELECT 1 FROM information_schema.tables"
            " WHERE table_schema = current_schema() AND table_name = ?",
            (name,),
        ).fetchone()
        return found is not None

    def optimize(self) -> None:
        self.execute("ANALYZE")

    def reload_statistics(self) -> None:
        """PostgreSQL shares statistics between sessions."""

    def close(self) -> None:
        self.raw.close()


def connect_postgres(url: str) -> PostgresConnection:
    """Opens a PostgreSQL connection (dev-only: migration portability checks)."""
    import psycopg  # noqa: PLC0415
    from psycopg.rows import dict_row  # noqa: PLC0415

    return PostgresConnection(psycopg.connect(url, autocommit=True, row_factory=dict_row))
