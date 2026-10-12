# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Migrations are portable SQL: they must also apply on PostgreSQL (SPEC §3, k8s-ready).

Runs only when UT_TEST_POSTGRES_URL points at a disposable database (CI contracts job,
`make contracts` locally). Each run works in a fresh schema that is dropped afterwards.
"""

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from ultimatetunes.db import migrate

CONTRACT_MIGRATIONS = Path(__file__).resolve().parents[3] / "contracts" / "db" / "migrations"
POSTGRES_URL = os.environ.get("UT_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(POSTGRES_URL is None, reason="UT_TEST_POSTGRES_URL not set"),
]


@pytest.fixture
def pg_schema() -> Iterator[object]:
    import psycopg  # noqa: PLC0415 - dev-only driver, imported only when the test runs

    assert POSTGRES_URL is not None
    schema = f"ut_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(POSTGRES_URL, autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA "{schema}"')
        conn.execute(f'SET search_path TO "{schema}"')
        try:
            yield conn
        finally:
            conn.execute(f'DROP SCHEMA "{schema}" CASCADE')


def apply_on_postgres(conn: object, directory: Path) -> int:
    import psycopg  # noqa: PLC0415

    assert isinstance(conn, psycopg.Connection)
    applied = 0
    for migration in migrate.discover(directory):
        with conn.transaction():
            for statement in migrate.split_statements(migration.sql):
                conn.execute(statement.encode())
        applied += 1
    return applied


def test_sample_portable_migration_applies(pg_schema: object, tmp_path: Path) -> None:
    (tmp_path / "0001_init.sql").write_text(
        "CREATE TABLE t (id TEXT PRIMARY KEY, n INTEGER NOT NULL DEFAULT 0);\n"
        "CREATE INDEX t_n ON t (n);\n",
        encoding="utf-8",
    )
    assert apply_on_postgres(pg_schema, tmp_path) == 1


def test_contract_migrations_apply_on_postgres(pg_schema: object) -> None:
    if not CONTRACT_MIGRATIONS.is_dir():
        pytest.skip("no contract migrations yet (PLAN T02)")
    assert apply_on_postgres(pg_schema, CONTRACT_MIGRATIONS) == len(
        migrate.discover(CONTRACT_MIGRATIONS)
    )
