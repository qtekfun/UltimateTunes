# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`JobQueue`: the download queue with leases (contracts/openapi/internal-worker.yaml).

Workers scale horizontally: a job is claimed with a **lease** that the worker keeps alive with
heartbeats. A lease that runs out sends the job back to `queued` (or to `failed` once its
attempts are used up) the next time anyone claims, so a killed worker never blocks a job.
One job row per (kind, track): requesting the same track twice returns the same job.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal, Protocol

from ultimatetunes.core.clock import Clock, format_ts
from ultimatetunes.db.database import Database
from ultimatetunes.db.driver import Connection
from ultimatetunes.db.repository import Repository
from ultimatetunes.errors import LeaseLost, NotFound
from ultimatetunes.ids import new_id

JobState = Literal["queued", "downloading", "tagging", "ready", "failed", "cancelled"]
ReleaseState = Literal["queued", "ready", "failed", "cancelled"]
LEASED_STATES = ("downloading", "tagging")

# Priorities (higher first), as in the comment of the `jobs` table.
PRIORITY_STREAM = 100
PRIORITY_PREFETCH = 50
PRIORITY_KEEP = 30
PRIORITY_IMPORT = 10


@dataclass(frozen=True)
class Job:
    id: str
    kind: str
    track_id: str
    yt_video_id: str
    state: str
    priority: int
    attempts: int
    max_attempts: int
    not_before: str | None
    lease_id: str | None
    lease_owner: str | None
    lease_expires_at: str | None
    error_code: str | None
    error_message: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Lease:
    lease_id: str
    expires_at: str
    heartbeat_s: int


@dataclass(frozen=True)
class Claimed:
    job: Job
    lease: Lease


class JobQueue(Protocol):
    def enqueue(
        self, *, track_id: str, video_id: str, priority: int, requested_by: str | None = None
    ) -> Job: ...

    def get(self, job_id: str) -> Job | None: ...

    def claim(
        self, worker_id: str, *, lease_s: int, kinds: tuple[str, ...] = ("download",)
    ) -> Claimed | None: ...

    def heartbeat(self, job_id: str, lease_id: str, *, lease_s: int) -> Lease: ...

    def release(  # noqa: PLR0913 - keyword-only fields of a release
        self,
        job_id: str,
        lease_id: str,
        *,
        state: ReleaseState,
        error_code: str | None = None,
        error_message: str | None = None,
        not_before: str | None = None,
    ) -> Job: ...

    def expire_leases(self) -> int: ...


_COLUMNS = (
    "id, kind, track_id, yt_video_id, state, priority, attempts, max_attempts, not_before,"
    " lease_id, lease_owner, lease_expires_at, error_code, error_message, created_at, updated_at"
)


class _Jobs(Repository):
    def by_id(self, job_id: str) -> Job | None:
        return self.one(Job, f"SELECT {_COLUMNS} FROM jobs WHERE id = ?", (job_id,))  # noqa: S608  # nosec B608

    def by_track(self, kind: str, track_id: str) -> Job | None:
        return self.one(
            Job,
            f"SELECT {_COLUMNS} FROM jobs WHERE kind = ? AND track_id = ?",  # noqa: S608  # nosec B608
            (kind, track_id),
        )


def _heartbeat_s(lease_s: int) -> int:
    return max(1, lease_s // 3)


class SqliteJobQueue:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    def _now(self) -> str:
        return format_ts(self._clock.now())

    def enqueue(
        self, *, track_id: str, video_id: str, priority: int, requested_by: str | None = None
    ) -> Job:
        now = self._now()
        with self._db.transaction() as conn:
            jobs = _Jobs(conn)
            existing = jobs.by_track("download", track_id)
            if existing is not None:
                if existing.state == "queued" and priority > existing.priority:
                    jobs.run(
                        "UPDATE jobs SET priority = ?, updated_at = ? WHERE id = ?",
                        (priority, now, existing.id),
                    )
                    return self._require(conn, existing.id)
                return existing
            job_id = new_id(self._clock)
            jobs.run(
                "INSERT INTO jobs (id, kind, track_id, yt_video_id, state, priority,"
                " requested_by, created_at, updated_at)"
                " VALUES (?, 'download', ?, ?, 'queued', ?, ?, ?, ?)",
                (job_id, track_id, video_id, priority, requested_by, now, now),
            )
            return self._require(conn, job_id)

    def _require(self, conn: Connection, job_id: str) -> Job:
        job = _Jobs(conn).by_id(job_id)
        if job is None:
            raise NotFound("No such job")
        return job

    def get(self, job_id: str) -> Job | None:
        with self._db.read() as conn:
            return _Jobs(conn).by_id(job_id)

    def _expire(self, conn: Connection, now: str) -> int:
        return conn.execute(
            "UPDATE jobs SET"
            " state = CASE WHEN attempts >= max_attempts THEN 'failed' ELSE 'queued' END,"
            " finished_at = CASE WHEN attempts >= max_attempts THEN ? ELSE NULL END,"
            " error_code = 'lease_expired', error_message = 'The lease ran out',"
            " lease_id = NULL, lease_owner = NULL, lease_expires_at = NULL, updated_at = ?"
            " WHERE state IN ('downloading', 'tagging') AND lease_expires_at <= ?",
            (now, now, now),
        ).rowcount

    def expire_leases(self) -> int:
        with self._db.transaction() as conn:
            return self._expire(conn, self._now())

    def claim(
        self, worker_id: str, *, lease_s: int, kinds: tuple[str, ...] = ("download",)
    ) -> Claimed | None:
        if not kinds:
            return None
        moment = self._clock.now()
        now = format_ts(moment)
        expires = format_ts(moment + timedelta(seconds=lease_s))
        marks = ", ".join("?" for _ in kinds)
        with self._db.transaction() as conn:
            self._expire(conn, now)
            row = conn.execute(
                f"SELECT id FROM jobs WHERE state = 'queued' AND kind IN ({marks})"  # noqa: S608  # nosec B608
                " AND (not_before IS NULL OR not_before <= ?)"
                " ORDER BY priority DESC, created_at ASC, id ASC LIMIT 1",
                (*kinds, now),
            ).fetchone()
            if row is None:
                return None
            job_id = str(row["id"])
            lease_id = new_id(self._clock)
            conn.execute(
                "UPDATE jobs SET state = 'downloading', attempts = attempts + 1,"
                " lease_id = ?, lease_owner = ?, lease_expires_at = ?, not_before = NULL,"
                " progress = 0, started_at = ?, updated_at = ? WHERE id = ?",
                (lease_id, worker_id, expires, now, now, job_id),
            )
            job = self._require(conn, job_id)
        return Claimed(job, Lease(lease_id, expires, _heartbeat_s(lease_s)))

    def _leased(self, conn: Connection, job_id: str, lease_id: str, now: str) -> Job:
        job = self._require(conn, job_id)
        if (
            job.lease_id != lease_id
            or job.state not in LEASED_STATES
            or job.lease_expires_at is None
            or job.lease_expires_at <= now
        ):
            raise LeaseLost()
        return job

    def heartbeat(self, job_id: str, lease_id: str, *, lease_s: int) -> Lease:
        moment = self._clock.now()
        now = format_ts(moment)
        expires = format_ts(moment + timedelta(seconds=lease_s))
        with self._db.transaction() as conn:
            self._leased(conn, job_id, lease_id, now)
            conn.execute(
                "UPDATE jobs SET lease_expires_at = ?, updated_at = ? WHERE id = ?",
                (expires, now, job_id),
            )
        return Lease(lease_id, expires, _heartbeat_s(lease_s))

    def release(  # noqa: PLR0913 - keyword-only fields of a release
        self,
        job_id: str,
        lease_id: str,
        *,
        state: ReleaseState,
        error_code: str | None = None,
        error_message: str | None = None,
        not_before: str | None = None,
    ) -> Job:
        now = self._now()
        finished = None if state == "queued" else now
        with self._db.transaction() as conn:
            self._leased(conn, job_id, lease_id, now)
            conn.execute(
                "UPDATE jobs SET state = ?, error_code = ?, error_message = ?, not_before = ?,"
                " lease_id = NULL, lease_owner = NULL, lease_expires_at = NULL,"
                " finished_at = ?, updated_at = ? WHERE id = ?",
                (state, error_code, error_message, not_before, finished, now, job_id),
            )
            return self._require(conn, job_id)
