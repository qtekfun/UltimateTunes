# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Worker status reports and admin commands (`PUT /internal/v1/workers/{workerId}/status`).

A report stores the worker's versions (`worker_status`), its last canary result once
(`canary_runs`, unique per worker and `at`), and hands out the pending admin commands
(`worker_commands`): those addressed to this worker, and those addressed to no worker that were
created before this report. Each command is delivered once, with a conditional update, so two
workers reporting at the same time never both get the same command.
"""

from dataclasses import dataclass

from ultimatetunes.core.clock import Clock, format_ts
from ultimatetunes.db.database import Database
from ultimatetunes.ids import new_id


@dataclass(frozen=True)
class CanaryResult:
    at: str
    ok: bool
    message: str | None


class WorkerRegistry:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    def report(
        self, worker_id: str, *, version: str, ytdlp_version: str, canary: CanaryResult | None
    ) -> list[str]:
        """Stores the report and returns the commands delivered to this worker now."""
        now = format_ts(self._clock.now())
        with self._db.transaction() as conn:
            updated = conn.execute(
                "UPDATE worker_status SET version = ?, ytdlp_version = ?, last_seen_at = ?"
                " WHERE worker_id = ?",
                (version, ytdlp_version, now, worker_id),
            ).rowcount
            if updated == 0:
                conn.execute(
                    "INSERT INTO worker_status (worker_id, version, ytdlp_version, last_seen_at)"
                    " VALUES (?, ?, ?, ?)",
                    (worker_id, version, ytdlp_version, now),
                )
            if canary is not None:
                conn.execute(
                    "INSERT INTO canary_runs (id, source, worker_id, ytdlp_version, ran_at, ok,"
                    " message) SELECT ?, 'worker', ?, ?, ?, ?, ? WHERE NOT EXISTS"
                    " (SELECT 1 FROM canary_runs WHERE source = 'worker' AND worker_id = ?"
                    " AND ran_at = ?)",
                    (
                        new_id(self._clock),
                        worker_id,
                        ytdlp_version,
                        canary.at,
                        1 if canary.ok else 0,
                        canary.message,
                        worker_id,
                        canary.at,
                    ),
                )
            pending = conn.execute(
                "SELECT id, command FROM worker_commands WHERE delivered_at IS NULL"
                " AND (worker_id = ? OR (worker_id IS NULL AND created_at <= ?))"
                " ORDER BY created_at ASC, id ASC",
                (worker_id, now),
            ).fetchall()
            delivered: list[str] = []
            for row in pending:
                taken = conn.execute(
                    "UPDATE worker_commands SET delivered_at = ?, delivered_to = ?"
                    " WHERE id = ? AND delivered_at IS NULL",
                    (now, worker_id, row["id"]),
                ).rowcount
                command = str(row["command"])
                if taken == 1 and command not in delivered:
                    delivered.append(command)
            return delivered
