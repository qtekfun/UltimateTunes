# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`JobQueue`: the download queue with leases (contracts/openapi/internal-worker.yaml).

Workers scale horizontally: a job is claimed with a **lease** that the worker keeps alive with
heartbeats. A lease that runs out sends the job back to `queued` (or to `failed` once its
attempts are used up, with its track; or to `cancelled` when an admin asked for it) the next
time anyone claims, so a killed worker never blocks a job. One job row per (kind, track):
requesting the same track twice returns the same job. Each attempt writes to its own staging
directory, `<job id>/<attempt>`.

`claim` takes a job with a conditional update and checks the row count, so two api replicas
(phase 5, PostgreSQL in READ COMMITTED) never hand out the same job. `release` (complete or
fail) is idempotent: the same call with the same lease returns the stored result.
"""

import json
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Literal, Protocol

from ultimatetunes.core.clock import Clock, format_ts
from ultimatetunes.db.database import Database
from ultimatetunes.db.driver import Connection
from ultimatetunes.db.repository import Repository
from ultimatetunes.errors import InvalidStateTransition, LeaseLost, NotFound
from ultimatetunes.ids import new_id

JobState = Literal["queued", "downloading", "tagging", "ready", "failed", "cancelled"]
ReleaseState = Literal["queued", "ready", "failed", "cancelled"]
LEASED_STATES = ("downloading", "tagging")
# A claim retries the selection this many times when another claimer took the candidate first.
CLAIM_TRIES = 3

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
    cancel_requested: int
    error_code: str | None
    error_message: str | None
    last_lease_id: str | None
    last_outcome: str | None
    created_at: str
    updated_at: str

    @property
    def staging_dir(self) -> str:
        """The staging directory of the current attempt (contract `Job.stagingDir`)."""
        return f"{self.id}/{self.attempts}"


@dataclass(frozen=True)
class Lease:
    lease_id: str
    expires_at: str
    heartbeat_s: int
    cancel_requested: bool = False


@dataclass(frozen=True)
class Claimed:
    job: Job
    lease: Lease


@dataclass(frozen=True)
class JobResult:
    """The contract's `JobResult`: what `complete` and `fail` answer."""

    job_id: str
    state: str
    attempts: int
    not_before: str | None


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
    ) -> JobResult:
        """Ends the lease (`ready`: complete, otherwise fail). Repeating the same call with the
        same lease returns the stored result; the other call is `InvalidStateTransition`."""
        ...

    def request_cancel(self, job_id: str) -> Job:
        """A queued job is cancelled at once (its track fails); a leased one gets
        `cancel_requested`, which the worker sees on its next heartbeat."""
        ...

    def expire_leases(self) -> int: ...


_COLUMNS = (
    "id, kind, track_id, yt_video_id, state, priority, attempts, max_attempts, not_before,"
    " lease_id, lease_owner, lease_expires_at, cancel_requested, error_code, error_message,"
    " last_lease_id, last_outcome, created_at, updated_at"
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


def _operation(state: ReleaseState) -> str:
    return "complete" if state == "ready" else "fail"


# Both statements match the leases whose time ran out (`lease_expires_at <= now`).
_FAIL_EXPIRED_TRACKS = (
    "UPDATE tracks SET status = 'failed', updated_at = ? WHERE status = 'pending'"
    " AND id IN (SELECT track_id FROM jobs WHERE state IN ('downloading', 'tagging')"
    " AND lease_expires_at <= ? AND (attempts >= max_attempts OR cancel_requested = 1))"
)
_EXPIRE_JOBS = (
    "UPDATE jobs SET"
    " state = CASE WHEN cancel_requested = 1 THEN 'cancelled'"
    " WHEN attempts >= max_attempts THEN 'failed' ELSE 'queued' END,"
    " finished_at = CASE WHEN cancel_requested = 1 OR attempts >= max_attempts"
    " THEN ? ELSE NULL END,"
    " error_code = CASE WHEN cancel_requested = 1 THEN 'cancelled' ELSE 'lease_expired' END,"
    " error_message = 'The lease ran out', cancel_requested = 0,"
    " lease_id = NULL, lease_owner = NULL, lease_expires_at = NULL,"
    " library_path = NULL, merge_into_track_id = NULL, updated_at = ?"
    " WHERE state IN ('downloading', 'tagging') AND lease_expires_at <= ?"
)


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
        # Tracks of the jobs that end now fail first, while those jobs still match.
        conn.execute(_FAIL_EXPIRED_TRACKS, (now, now))
        return conn.execute(_EXPIRE_JOBS, (now, now, now)).rowcount

    def expire_leases(self) -> int:
        with self._db.transaction() as conn:
            return self._expire(conn, self._now())

    def _take(  # noqa: PLR0913 - the fields of one conditional update
        self,
        conn: Connection,
        job_id: str,
        *,
        worker_id: str,
        lease_id: str,
        now: str,
        expires: str,
    ) -> bool:
        """Takes a queued job; False when another claimer took it first (zero rows)."""
        taken = conn.execute(
            "UPDATE jobs SET state = 'downloading', attempts = attempts + 1,"
            " lease_id = ?, lease_owner = ?, lease_expires_at = ?, not_before = NULL,"
            " progress = 0, bytes_downloaded = NULL, expected_size = NULL, part_path = NULL,"
            " final_path = NULL, finished = 0, started_at = ?, updated_at = ?"
            " WHERE id = ? AND state = 'queued' AND lease_id IS NULL"
            " AND (not_before IS NULL OR not_before <= ?)",
            (lease_id, worker_id, expires, now, now, job_id, now),
        ).rowcount
        return taken == 1

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
            for _ in range(CLAIM_TRIES):
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
                if self._take(
                    conn, job_id, worker_id=worker_id, lease_id=lease_id, now=now, expires=expires
                ):
                    job = self._require(conn, job_id)
                    return Claimed(job, Lease(lease_id, expires, _heartbeat_s(lease_s)))
        return None

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
            job = self._leased(conn, job_id, lease_id, now)
            conn.execute(
                "UPDATE jobs SET lease_expires_at = ?, updated_at = ? WHERE id = ?",
                (expires, now, job_id),
            )
        return Lease(lease_id, expires, _heartbeat_s(lease_s), bool(job.cancel_requested))

    def release(  # noqa: PLR0913 - keyword-only fields of a release
        self,
        job_id: str,
        lease_id: str,
        *,
        state: ReleaseState,
        error_code: str | None = None,
        error_message: str | None = None,
        not_before: str | None = None,
    ) -> JobResult:
        now = self._now()
        operation = _operation(state)
        with self._db.transaction() as conn:
            current = self._require(conn, job_id)
            if current.last_lease_id == lease_id and current.lease_id != lease_id:
                return self._repeated(current, operation)
            job = self._leased(conn, job_id, lease_id, now)
            result = JobResult(
                job_id, state, job.attempts, not_before if state == "queued" else None
            )
            outcome = json.dumps({"operation": operation, **asdict(result)})
            keep = 1 if state == "ready" else 0
            conn.execute(
                "UPDATE jobs SET state = ?, error_code = ?, error_message = ?, not_before = ?,"
                " lease_id = NULL, lease_owner = NULL, lease_expires_at = NULL,"
                " cancel_requested = 0, last_lease_id = ?, last_outcome = ?,"
                " library_path = CASE WHEN ? = 1 THEN library_path ELSE NULL END,"
                " merge_into_track_id = CASE WHEN ? = 1 THEN merge_into_track_id ELSE NULL END,"
                " finished_at = ?, updated_at = ? WHERE id = ? AND lease_id = ?",
                (
                    state,
                    error_code,
                    error_message,
                    result.not_before,
                    lease_id,
                    outcome,
                    keep,
                    keep,
                    None if state == "queued" else now,
                    now,
                    job_id,
                    lease_id,
                ),
            )
            if state in ("failed", "cancelled"):
                self._fail_track(conn, job.track_id, now)
        return result

    @staticmethod
    def _repeated(job: Job, operation: str) -> JobResult:
        """The stored result of a release repeated with the same lease."""
        stored = json.loads(job.last_outcome or "{}")
        if stored.get("operation") != operation:
            raise InvalidStateTransition("The lease was already released by another call")
        return JobResult(
            str(stored["job_id"]),
            str(stored["state"]),
            int(stored["attempts"]),
            stored["not_before"],
        )

    @staticmethod
    def _fail_track(conn: Connection, track_id: str, now: str) -> None:
        conn.execute(
            "UPDATE tracks SET status = 'failed', updated_at = ?"
            " WHERE id = ? AND status = 'pending'",
            (now, track_id),
        )

    def request_cancel(self, job_id: str) -> Job:
        now = self._now()
        with self._db.transaction() as conn:
            job = self._require(conn, job_id)
            if job.state == "queued":
                conn.execute(
                    "UPDATE jobs SET state = 'cancelled', error_code = 'cancelled',"
                    " error_message = 'Cancelled by an admin', finished_at = ?, updated_at = ?"
                    " WHERE id = ?",
                    (now, now, job_id),
                )
                self._fail_track(conn, job.track_id, now)
            elif job.state in LEASED_STATES:
                conn.execute(
                    "UPDATE jobs SET cancel_requested = 1, updated_at = ? WHERE id = ?",
                    (now, job_id),
                )
            return self._require(conn, job_id)
