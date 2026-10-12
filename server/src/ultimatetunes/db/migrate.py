# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Applies the plain SQL migrations of `contracts/db/migrations` in order.

Migrations are portable SQL (SQLite and PostgreSQL). Each file runs in its own transaction and
is recorded in `schema_migrations`; applied files are never run again. The api never migrates:
`ultimatetunes migrate` does (a Kubernetes Job later), and `/readyz` checks the result.
"""

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

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


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY,"
        " name TEXT NOT NULL,"
        " applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )


def applied_versions(conn: sqlite3.Connection) -> set[int]:
    """Versions already applied; read-only, so `/readyz` can call it on a read-only connection."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    if exists is None:
        return set()
    return {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}


def pending(conn: sqlite3.Connection, directory: Path) -> list[Migration]:
    done = applied_versions(conn)
    return [m for m in discover(directory) if m.version not in done]


def connect(database: Path) -> sqlite3.Connection:
    """SQLite connection in WAL mode, autocommit off only inside explicit transactions."""
    database.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def migrate(conn: sqlite3.Connection, directory: Path) -> list[Migration]:
    """Applies every pending migration, one transaction each. Returns what was applied."""
    _ensure_table(conn)
    applied: list[Migration] = []
    for migration in pending(conn, directory):
        conn.execute("BEGIN")
        try:
            for statement in split_statements(migration.sql):
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                (migration.version, migration.name),
            )
        except Exception:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        applied.append(migration)
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
