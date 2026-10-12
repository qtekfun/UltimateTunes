# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Api side of the canary in the database.

- `record` stores a catalog run in `canary_runs` (source `api`, one entry per check in
  `detail`). The admin panel lists it, and the notification sweep (T15) sends the failed ones.
- `claim` decides whether this api runs the catalog checks now: when the last run started at
  least one interval ago, or when an admin asked for a run (`worker_commands.run_canary`)
  after it. The start time lives in `settings` (`canary.api.started_at`) and moves with a
  compare-and-set, so with several api replicas exactly one of them runs. The admin request
  is only read here: the worker still receives it and runs its download check.
"""

from datetime import datetime, timedelta

from ultimatetunes.canary.checks import Report
from ultimatetunes.core.clock import Clock, format_ts, parse_ts
from ultimatetunes.db.database import Database
from ultimatetunes.db.driver import Connection, IntegrityError
from ultimatetunes.ids import new_id

KEY_STARTED = "canary.api.started_at"


class CanaryStore:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    def record(self, report: Report) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO canary_runs (id, source, worker_id, ytdlp_version, ran_at, ok,"
                " message, detail) VALUES (?, ?, NULL, NULL, ?, ?, ?, ?)",
                (
                    new_id(self._clock),
                    report.source,
                    report.ran_at,
                    1 if report.ok else 0,
                    report.message,
                    report.detail_json(),
                ),
            )

    def last_started(self) -> datetime | None:
        with self._db.read() as conn:
            return _started(conn)

    def due(self, interval: timedelta, *, scheduled: bool = True) -> bool:
        """A run is due when scheduled runs are on and the last one started an interval ago
        (or never), or when an admin asked for one since."""
        with self._db.read() as conn:
            return self._due(conn, _started(conn), interval, scheduled=scheduled)

    def claim(self, interval: timedelta, *, scheduled: bool = True) -> bool:
        """True when this caller runs the checks now (the start time moved to now)."""
        now = format_ts(self._clock.now())
        try:
            with self._db.transaction() as conn:
                current = conn.execute(
                    "SELECT value FROM settings WHERE key = ?", (KEY_STARTED,)
                ).scalar()
                started = parse_ts(str(current)) if current is not None else None
                if not self._due(conn, started, interval, scheduled=scheduled):
                    return False
                if current is None:
                    conn.execute(
                        "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                        (KEY_STARTED, now, now),
                    )
                    return True
                # Compare-and-set on the value read above: another replica that moved it
                # first wins.
                moved = conn.execute(
                    "UPDATE settings SET value = ?, updated_at = ? WHERE key = ? AND value = ?",
                    (now, now, KEY_STARTED, current),
                ).rowcount
                return moved == 1
        except IntegrityError:
            return False  # another replica inserted the first start time at the same moment

    def _due(
        self, conn: Connection, started: datetime | None, interval: timedelta, *, scheduled: bool
    ) -> bool:
        if started is None:
            return scheduled or self._requested(conn, None)
        if scheduled and self._clock.now() - started >= interval:
            return True
        return self._requested(conn, format_ts(started))

    @staticmethod
    def _requested(conn: Connection, since: str | None) -> bool:
        sql = "SELECT 1 FROM worker_commands WHERE command = 'run_canary'"
        params: tuple[str, ...] = ()
        if since is not None:
            sql += " AND created_at > ?"
            params = (since,)
        return conn.execute(sql, params).fetchone() is not None


def _started(conn: Connection) -> datetime | None:
    value = conn.execute("SELECT value FROM settings WHERE key = ?", (KEY_STARTED,)).scalar()
    return parse_ts(str(value)) if value is not None else None
