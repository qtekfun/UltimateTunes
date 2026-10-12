# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The queue, the merge and the worker registry run unchanged on PostgreSQL (portable SQL).

Runs only when UT_TEST_POSTGRES_URL points at a disposable database (CI contracts job,
`make contracts` locally), in a fresh schema dropped afterwards.
"""

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.jobs.test_archive import seed_references
from tests.jobs.test_queue import add_track, report
from ultimatetunes.core.clock import FakeClock, format_ts
from ultimatetunes.core.storage import LocalLibraryStore
from ultimatetunes.db import Database, migrate
from ultimatetunes.db.driver import PostgresConnection, connect_postgres
from ultimatetunes.jobs.archive import archive_finalizer
from ultimatetunes.jobs.queue import SqliteJobQueue
from ultimatetunes.jobs.workers import CanaryResult, WorkerRegistry

CONTRACT_MIGRATIONS = Path(__file__).resolve().parents[3] / "contracts" / "db" / "migrations"
POSTGRES_URL = os.environ.get("UT_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(POSTGRES_URL is None, reason="UT_TEST_POSTGRES_URL not set"),
]


@pytest.fixture
def pg_db(clock: FakeClock) -> Iterator[Database]:
    assert POSTGRES_URL is not None
    url = POSTGRES_URL
    name = f"ut_{uuid.uuid4().hex[:12]}"
    admin = connect_postgres(url)
    admin.execute(f'CREATE SCHEMA "{name}"')

    def opener() -> PostgresConnection:
        conn = connect_postgres(url)
        conn.execute(f'SET search_path TO "{name}"')
        return conn

    setup = opener()
    migrate.migrate(setup, CONTRACT_MIGRATIONS, clock)
    setup.close()
    database = Database(opener)
    try:
        yield database
    finally:
        database.close()
        admin.execute(f'DROP SCHEMA "{name}" CASCADE')
        admin.close()


def test_a_job_lifecycle_on_postgres(pg_db: Database, clock: FakeClock, tmp_path: Path) -> None:
    add_track(pg_db, clock, "pending", "Rb8Tn3ZcYv0")
    seed_references(pg_db, clock)
    queue = SqliteJobQueue(pg_db, clock, rand=lambda: 0.5)
    job = queue.enqueue(track_id="pending", video_id="Rb8Tn3ZcYv0", priority=100)
    first = queue.claim("w1", lease_s=30)
    assert first is not None
    queue.progress(job.id, first.lease.lease_id, report(first))
    queue.heartbeat(job.id, first.lease.lease_id, lease_s=30)
    failed = queue.fail(
        job.id, first.lease.lease_id, error_code="network_error", retryable=True, message="x"
    )
    assert failed.state == "queued"
    clock.advance(31)
    second = queue.claim("w1", lease_s=30)
    assert second is not None
    assert (second.job.previous_format_id, second.job.previous_expected_size) == ("251", 200)
    queue.progress(job.id, second.lease.lease_id, report(second, state="tagging", finished=True))
    with pg_db.transaction() as conn:
        conn.execute("UPDATE jobs SET merge_into_track_id = 'kept' WHERE id = ?", (job.id,))
    library = LocalLibraryStore(tmp_path)
    finalize = archive_finalizer(
        library, track_id="kept", library_path=None, now=format_ts(clock.now())
    )
    assert queue.complete(job.id, second.lease.lease_id, finalize).state == "ready"
    with pg_db.read() as conn:
        stats = conn.execute(
            "SELECT user_id, play_count FROM user_track_stats ORDER BY user_id"
        ).fetchall()
        stars = conn.execute("SELECT COUNT(*) AS n FROM starred_tracks").scalar()
    assert [dict(r) for r in stats] == [
        {"user_id": "ana", "play_count": 5},
        {"user_id": "ben", "play_count": 1},
    ]
    assert stars == 2
    requeued = queue.request_cancel(job.id)
    assert requeued.state == "ready"
    assert queue.expire_leases() == 0


def test_worker_reports_on_postgres(pg_db: Database, clock: FakeClock) -> None:
    with pg_db.transaction() as conn:
        conn.execute(
            "INSERT INTO worker_commands (id, command, created_at)"
            " VALUES ('c1', 'update_ytdlp', '2026-10-12T07:00:00.000Z')"
        )
    registry = WorkerRegistry(pg_db, clock)
    canary = CanaryResult("2026-10-12T03:00:00.000Z", ok=True, message=None)
    assert registry.report("w1", version="v", ytdlp_version="y", canary=canary) == ["update_ytdlp"]
    assert registry.report("w1", version="v", ytdlp_version="y", canary=canary) == []
    with pg_db.read() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM canary_runs").scalar() == 1
