# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Applies the plain SQL migrations of `contracts/db/migrations` in order.

Migrations are portable SQL (SQLite and PostgreSQL, through `db.driver`). Each file runs in its
own transaction and is recorded in `schema_migrations`; applied files are never run again. The
api never migrates: `ultimatetunes migrate` does (a Kubernetes Job later), and `/readyz` checks
the result. It ends by refreshing the planner statistics (`Connection.optimize`).
"""

import re
from dataclasses import dataclass
from pathlib import Path

from ultimatetunes.core.clock import Clock, SystemClock, format_ts
from ultimatetunes.db.driver import Connection, SqliteConnection, connect_sqlite

_NAME = re.compile(r"^(?P<version>\d{4})_[a-z0-9_]+\.sql$")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


def discover(directory: Path) -> list[Migration]:
    """Migrations found in `directory`, ordered by version. Non-matching files are an error."""
    migrations: list[Migration] = []
    if not directory.is_dir():
        raise FileNotFoundError(f"migrations directory not found: {directory}")
    for path in sorted(directory.glob("*.sql")):
        match = _NAME.match(path.name)
        if match is None:
            raise ValueError(f"bad migration file name: {path.name} (expected NNNN_name.sql)")
        migrations.append(
            Migration(int(match["version"]), path.name, path.read_text(encoding="utf-8"))
        )
    versions = [m.version for m in migrations]
    if len(set(versions)) != len(versions):
        raise ValueError("two migrations share a version number")
    return migrations


def _ensure_table(conn: Connection) -> None:
    if not conn.table_exists("schema_migrations"):
        conn.execute(
            "CREATE TABLE schema_migrations ("
            " version INTEGER NOT NULL PRIMARY KEY,"
            " name TEXT NOT NULL,"
            " applied_at TEXT NOT NULL)"
        )


def applied_versions(conn: Connection) -> set[int]:
    """Versions already applied; read-only, so `/readyz` can call it on a read-only connection."""
    if not conn.table_exists("schema_migrations"):
        return set()
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {int(str(row["version"])) for row in rows}


def pending(conn: Connection, directory: Path) -> list[Migration]:
    done = applied_versions(conn)
    return [m for m in discover(directory) if m.version not in done]


def connect(database: Path) -> SqliteConnection:
    """SQLite connection for the migrator (WAL, foreign keys on). See `db.driver`."""
    return connect_sqlite(database)


def migrate(conn: Connection, directory: Path, clock: Clock | None = None) -> list[Migration]:
    """Applies every pending migration, one transaction each. Returns what was applied."""
    clock = clock or SystemClock()
    _ensure_table(conn)
    applied: list[Migration] = []
    for migration in pending(conn, directory):
        with conn.transaction():
            for statement in split_statements(migration.sql):
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (migration.version, migration.name, format_ts(clock.now())),
            )
        applied.append(migration)
    # New tables and indexes need planner statistics (issue #54); cheap when nothing changed.
    conn.optimize()
    return applied


_STATEMENT_END = re.compile(r";[ \t]*$", re.MULTILINE)


def split_statements(sql: str) -> list[str]:
    """Splits a migration into statements on a `;` that ends a line; whole-line `--` comments
    are dropped.

    Rules for migration authors (contracts/db/README.md): end every statement with `;` at the
    end of a line, never end a line inside a statement with `;`, and keep comments on their own
    lines. A `;` inside a line (e.g. `DEFAULT ';'`) is left alone.
    """
    lines = [line for line in sql.splitlines() if not line.lstrip().startswith("--")]
    return [s.strip() for s in _STATEMENT_END.split("\n".join(lines)) if s.strip()]
