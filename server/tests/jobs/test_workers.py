# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Worker status reports: versions, canary results stored once, commands delivered once."""

from ultimatetunes.core.clock import FakeClock
from ultimatetunes.db import Database
from ultimatetunes.jobs.workers import CanaryResult, WorkerRegistry


def add_command(db: Database, command_id: str, command: str, worker: str | None, at: str) -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO worker_commands (id, command, worker_id, created_at) VALUES (?, ?, ?, ?)",
            (command_id, command, worker, at),
        )


def test_a_report_stores_versions_and_the_canary_once(db: Database, clock: FakeClock) -> None:
    registry = WorkerRegistry(db, clock)
    canary = CanaryResult("2026-10-12T03:00:00.000Z", ok=True, message=None)
    assert registry.report("w1", version="0.1.0", ytdlp_version="2026.08.19", canary=canary) == []
    clock.advance(60)
    registry.report("w1", version="0.1.1", ytdlp_version="2026.09.28", canary=canary)
    registry.report("w1", version="0.1.1", ytdlp_version="2026.09.28", canary=None)
    with db.read() as conn:
        status = conn.execute("SELECT * FROM worker_status").fetchall()
        runs = conn.execute("SELECT worker_id, ok, ytdlp_version FROM canary_runs").fetchall()
    assert [dict(r) for r in status] == [
        {
            "worker_id": "w1",
            "version": "0.1.1",
            "ytdlp_version": "2026.09.28",
            "last_seen_at": "2026-10-12T08:01:00.000Z",
        }
    ]
    assert [dict(r) for r in runs] == [{"worker_id": "w1", "ok": 1, "ytdlp_version": "2026.08.19"}]
    failed = CanaryResult("2026-10-13T03:00:00.000Z", ok=False, message="bot wall")
    registry.report("w1", version="0.1.1", ytdlp_version="2026.09.28", canary=failed)
    with db.read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM canary_runs").scalar() == 2


def test_commands_are_delivered_once_to_the_right_worker(db: Database, clock: FakeClock) -> None:
    registry = WorkerRegistry(db, clock)
    add_command(db, "c1", "update_ytdlp", None, "2026-10-12T07:59:00.000Z")
    add_command(db, "c2", "run_canary", "w2", "2026-10-12T07:59:00.000Z")
    add_command(db, "c3", "update_ytdlp", "w1", "2026-10-12T07:59:30.000Z")
    # Created after this report: the next report gets it.
    add_command(db, "c4", "run_canary", None, "2026-10-12T08:00:30.000Z")
    assert registry.report("w1", version="v", ytdlp_version="y", canary=None) == ["update_ytdlp"]
    assert registry.report("w1", version="v", ytdlp_version="y", canary=None) == []
    assert registry.report("w2", version="v", ytdlp_version="y", canary=None) == ["run_canary"]
    clock.advance(60)
    assert registry.report("w1", version="v", ytdlp_version="y", canary=None) == ["run_canary"]
    with db.read() as conn:
        delivered = conn.execute(
            "SELECT id, delivered_to FROM worker_commands ORDER BY id"
        ).fetchall()
    assert [dict(r) for r in delivered] == [
        {"id": "c1", "delivered_to": "w1"},
        {"id": "c2", "delivered_to": "w2"},
        {"id": "c3", "delivered_to": "w1"},
        {"id": "c4", "delivered_to": "w1"},
    ]
