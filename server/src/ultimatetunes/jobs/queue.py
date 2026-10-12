# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`JobQueue`: the download queue with leases (contracts/openapi/internal-worker.yaml).

Workers scale horizontally: a job is claimed with a **lease** that the worker keeps alive with
heartbeats (or progress reports). A lease that runs out sends the job back to `queued` (or to
`failed` once its attempts are used up, with its track; or to `cancelled` when an admin asked
for it) the next time anyone claims, so a killed worker never blocks a job. One job row per
(kind, track), and one track per video id: requesting the same video twice returns the same
job; requesting a `failed` or `cancelled` one queues it again with its attempts reset. Each
attempt writes to its own staging directory, `<job id>/<attempt>`.

`claim` takes a job with a conditional update and checks the row count, so two api replicas
(phase 5, PostgreSQL in READ COMMITTED) never hand out the same job. `complete` and `fail` are
idempotent: the same call with the same lease returns the stored result. Which moves are
allowed, and where a failure goes, is decided by `state.py` (the state machine).
"""

import json
import secrets
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Literal, Protocol

from ultimatetunes.core.clock import Clock, format_ts
from ultimatetunes.core.storage import check_relative
from ultimatetunes.db.database import Database
from ultimatetunes.db.driver import Connection
from ultimatetunes.db.repository import Repository
from ultimatetunes.errors import InvalidStateTransition, LeaseLost, NotFound, PathRejected
from ultimatetunes.ids import new_id
from ultimatetunes.jobs import state as sm
from ultimatetunes.jobs.gate import DownloadGate

JobState = Literal["queued", "downloading", "tagging", "ready", "failed", "cancelled"]
ReleaseState = Literal["queued", "ready", "failed", "cancelled"]
LEASED_STATES = ("downloading", "tagging")
# A claim retries the selection this many times when another claimer took the candidate first.
CLAIM_TRIES = 3
# Lease extension of a progress report when the claim did not record one.
DEFAULT_LEASE_S = 60

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
    progress: float = 0.0
    bytes_downloaded: int | None = None
    expected_size: int | None = None
    part_path: str | None = None
    final_path: str | None = None
    finished: bool = False
    progressive: bool = False
    format_id: str | None = None
    content_type: str | None = None
    library_path: str | None = None
    merge_into_track_id: str | None = None
    previous_format_id: str | None = None
    previous_expected_size: int | None = None
    lease_seconds: int | None = None
    attempt_seq: int = 0

    @property
    def staging_dir(self) -> str:
        """The staging directory of the current attempt (contract `Job.stagingDir`): numbered by
        the job's claim sequence, which never resets, so a re-request never reuses one."""
        return f"{self.id}/{self.attempt_seq}"


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


@dataclass(frozen=True)
class ProgressReport:
    """The contract's `Progress` (without the lease id)."""

    state: str
    progress: float
    bytes_downloaded: int
    expected_size: int | None
    part_path: str
    final_path: str
    finished: bool
    format_id: str
    content_type: str
    progressive: bool


@dataclass(frozen=True)
class JobHints:
    """The contract's `JobHints`, from the pending track's YouTube Music metadata."""

    title: str
    artist_name: str
    album_name: str | None
    yt_album_browse_id: str | None
    yt_artist_channel_id: str | None
    duration_ms: int | None
    year: int | None
    track_number: int | None
    yt_thumbnail_url: str | None


# Runs inside the release transaction, after the lease check and before the job row changes
# (e.g. `complete` checks the archived file and updates the track). Raising rolls it all back.
Finalizer = Callable[[Connection, Job], None]


class JobQueue(Protocol):
    def enqueue(
        self, *, track_id: str, video_id: str, priority: int, requested_by: str | None = None
    ) -> Job: ...

    def enqueue_in(
        self,
        conn: Connection,
        *,
        track_id: str,
        video_id: str,
        priority: int,
        requested_by: str | None = None,
    ) -> Job:
        """`enqueue` inside the caller's transaction, so creating a track and its job is one
        atomic step (contracts/ids.md, materialization)."""
        ...

    def get(self, job_id: str) -> Job | None: ...

    def by_video(self, video_id: str) -> Job | None: ...

    def hints(self, job: Job) -> JobHints: ...

    def claim(
        self, worker_id: str, *, lease_s: int, kinds: tuple[str, ...] = ("download",)
    ) -> Claimed | None: ...

    def heartbeat(self, job_id: str, lease_id: str, *, lease_s: int) -> Lease: ...

    def progress(self, job_id: str, lease_id: str, report: ProgressReport) -> Lease: ...

    def release(  # noqa: PLR0913 - keyword-only fields of a release
        self,
        job_id: str,
        lease_id: str,
        *,
        state: ReleaseState,
        error_code: str | None = None,
        error_message: str | None = None,
        not_before: str | None = None,
        finalize: Finalizer | None = None,
    ) -> JobResult:
        """Ends the lease (`ready`: complete, otherwise fail). Repeating the same call with the
        same lease returns the stored result; the other call is `InvalidStateTransition`."""
        ...

    def fail(
        self, job_id: str, lease_id: str, *, error_code: str, retryable: bool, message: str
    ) -> JobResult:
        """A worker failure: retry with backoff, or end `failed`/`cancelled` (state.py)."""
        ...

    def complete(self, job_id: str, lease_id: str, finalize: Finalizer) -> JobResult: ...

    def request_cancel(self, job_id: str) -> Job:
        """A queued job is cancelled at once (its track fails); a leased one gets
        `cancel_requested`, which the worker sees on its next heartbeat."""
        ...

    def expire_leases(self) -> int: ...


_COLUMNS = (
    "id, kind, track_id, yt_video_id, state, priority, attempts, max_attempts, not_before,"
    " lease_id, lease_owner, lease_expires_at, cancel_requested, error_code, error_message,"
    " last_lease_id, last_outcome, created_at, updated_at, progress, bytes_downloaded,"
    " expected_size, part_path, final_path, finished, progressive, format_id, content_type,"
    " library_path, merge_into_track_id, previous_format_id, previous_expected_size,"
    " lease_seconds, attempt_seq"
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

    def by_video(self, video_id: str) -> Job | None:
        return self.one(
            Job,
            f"SELECT {_COLUMNS} FROM jobs WHERE kind = 'download' AND yt_video_id = ?"  # noqa: S608  # nosec B608
            " ORDER BY created_at ASC, id ASC LIMIT 1",
            (video_id,),
        )

    def hints(self, track_id: str) -> JobHints | None:
        return self.one(
            JobHints,
            "SELECT title, artist_name, album_name, yt_album_browse_id, yt_artist_channel_id,"
            " duration_ms, year, track_number, yt_thumbnail_url FROM tracks WHERE id = ?",
            (track_id,),
        )


def _heartbeat_s(lease_s: int) -> int:
    return max(1, lease_s // 3)


def _operation(state: str) -> str:
    return "complete" if state == "ready" else "fail"


def _inside(staging_dir: str, path: str) -> str:
    """A staging path of the current attempt: normalized and inside its `stagingDir`."""
    clean = check_relative(path)
    if not clean.startswith(staging_dir + "/"):
        raise PathRejected("path is outside the job's stagingDir")
    return clean


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
# A new attempt: the previous attempt's format and exact size move to previous_* (only when it
# reported a format, so an attempt that died before its first report erases nothing), and the
# streaming columns start empty.
_TAKE = (
    "UPDATE jobs SET state = 'downloading', attempts = attempts + 1, attempt_seq = attempt_seq + 1,"
    " lease_id = ?, lease_owner = ?, lease_expires_at = ?, lease_seconds = ?, not_before = NULL,"
    " previous_expected_size = CASE WHEN format_id IS NULL THEN previous_expected_size"
    " ELSE expected_size END,"
    " previous_format_id = CASE WHEN format_id IS NULL THEN previous_format_id"
    " ELSE format_id END,"
    " progress = 0, bytes_downloaded = NULL, expected_size = NULL, part_path = NULL,"
    " final_path = NULL, finished = 0, progressive = 0, format_id = NULL, content_type = NULL,"
    " started_at = ?, updated_at = ?"
    " WHERE id = ? AND state = 'queued' AND lease_id IS NULL"
    " AND (not_before IS NULL OR not_before <= ?)"
)


class SqliteJobQueue:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        *,
        rand: Callable[[], float] | None = None,
        gate: DownloadGate | None = None,
    ) -> None:
        self._db = db
        self._clock = clock
        self._rand = rand or secrets.SystemRandom().random
        # The abuse limits (jobs/gate.py); None (tests of the queue alone) checks nothing.
        self._gate = gate

    def _admit(self, conn: Connection, track_id: str, requested_by: str | None) -> None:
        """A download is about to start for `track_id`: the gate may refuse it."""
        if self._gate is not None:
            self._gate.check_new_download(conn, track_id, requested_by)

    def _now(self) -> str:
        return format_ts(self._clock.now())

    def enqueue(
        self, *, track_id: str, video_id: str, priority: int, requested_by: str | None = None
    ) -> Job:
        with self._db.transaction() as conn:
            return self.enqueue_in(
                conn,
                track_id=track_id,
                video_id=video_id,
                priority=priority,
                requested_by=requested_by,
            )

    def enqueue_in(
        self,
        conn: Connection,
        *,
        track_id: str,
        video_id: str,
        priority: int,
        requested_by: str | None = None,
    ) -> Job:
        now = self._now()
        jobs = _Jobs(conn)
        existing = jobs.by_track("download", track_id)
        if existing is None:
            self._admit(conn, track_id, requested_by)
            job_id = new_id(self._clock)
            jobs.run(
                "INSERT INTO jobs (id, kind, track_id, yt_video_id, state, priority,"
                " requested_by, created_at, updated_at)"
                " VALUES (?, 'download', ?, ?, 'queued', ?, ?, ?, ?)",
                (job_id, track_id, video_id, priority, requested_by, now, now),
            )
            return self._require(conn, job_id)
        if existing.state in (sm.JobState.FAILED, sm.JobState.CANCELLED):
            self._admit(conn, track_id, requested_by)
            self._requeue(conn, existing, priority, now, requested_by)
        elif existing.state == sm.JobState.QUEUED and priority > existing.priority:
            jobs.run(
                "UPDATE jobs SET priority = ?, updated_at = ? WHERE id = ?",
                (priority, now, existing.id),
            )
        return self._require(conn, existing.id)

    @staticmethod
    def _requeue(
        conn: Connection, job: Job, priority: int, now: str, requested_by: str | None
    ) -> None:
        """A new request for a failed or cancelled job: back to the queue, attempts reset,
        its track pending again (ut-v1 `requestTrack`). The new requester is charged for it
        (abuse limits), unless the request has no user."""
        sm.check_transition(job.state, sm.JobState.QUEUED)
        conn.execute(
            "UPDATE jobs SET state = 'queued', attempts = 0, priority = ?, not_before = NULL,"
            " error_code = NULL, error_message = NULL, cancel_requested = 0,"
            " requested_by = COALESCE(?, requested_by),"
            " finished_at = NULL, updated_at = ? WHERE id = ?",
            (priority, requested_by, now, job.id),
        )
        conn.execute(
            "UPDATE tracks SET status = 'pending', updated_at = ?"
            " WHERE id = ? AND status = 'failed'",
            (now, job.track_id),
        )

    def _require(self, conn: Connection, job_id: str) -> Job:
        job = _Jobs(conn).by_id(job_id)
        if job is None:
            raise NotFound("No such job")
        return job

    def get(self, job_id: str) -> Job | None:
        with self._db.read() as conn:
            return _Jobs(conn).by_id(job_id)

    def by_video(self, video_id: str) -> Job | None:
        with self._db.read() as conn:
            return _Jobs(conn).by_video(video_id)

    def hints(self, job: Job) -> JobHints:
        with self._db.read() as conn:
            found = _Jobs(conn).hints(job.track_id)
        if found is None:
            raise NotFound("No such track")
        return found

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
        lease_s: int = DEFAULT_LEASE_S,
    ) -> bool:
        """Takes a queued job; False when another claimer took it first (zero rows)."""
        taken = conn.execute(
            _TAKE, (lease_id, worker_id, expires, lease_s, now, now, job_id, now)
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
            if self._gate is not None and not self._gate.has_space():
                # Low disk space: queued jobs wait (abuse limits, `UT_MIN_FREE_BYTES`).
                return None
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
                    conn,
                    job_id,
                    worker_id=worker_id,
                    lease_id=lease_id,
                    now=now,
                    expires=expires,
                    lease_s=lease_s,
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
                "UPDATE jobs SET lease_expires_at = ?, lease_seconds = ?, updated_at = ?"
                " WHERE id = ?",
                (expires, lease_s, now, job_id),
            )
        return Lease(lease_id, expires, _heartbeat_s(lease_s), bool(job.cancel_requested))

    def progress(self, job_id: str, lease_id: str, report: ProgressReport) -> Lease:
        """Stores the attempt's streaming state and extends the lease like a heartbeat.
        Last write wins, but `progress`, `bytesDownloaded` and `finished` never go back, and
        `expectedSize`/`formatId` are fixed once reported."""
        moment = self._clock.now()
        now = format_ts(moment)
        with self._db.transaction() as conn:
            job = self._leased(conn, job_id, lease_id, now)
            target = sm.check_report(job.state, report.state)
            part = sm.check_fixed(
                "partPath", job.part_path, _inside(job.staging_dir, report.part_path)
            )
            final = sm.check_fixed(
                "finalPath", job.final_path, _inside(job.staging_dir, report.final_path)
            )
            size = sm.check_expected_size(job.expected_size, report.expected_size)
            format_id = sm.check_fixed("formatId", job.format_id, report.format_id)
            lease_s = job.lease_seconds or DEFAULT_LEASE_S
            expires = format_ts(moment + timedelta(seconds=lease_s))
            updated = conn.execute(
                "UPDATE jobs SET state = ?, progress = ?, bytes_downloaded = ?,"
                " expected_size = ?, part_path = ?, final_path = ?, finished = ?,"
                " progressive = ?, format_id = ?, content_type = ?, lease_expires_at = ?,"
                " updated_at = ? WHERE id = ? AND lease_id = ?",
                (
                    target.value,
                    max(job.progress, min(max(report.progress, 0.0), 1.0)),
                    max(job.bytes_downloaded or 0, report.bytes_downloaded),
                    size,
                    part,
                    final,
                    1 if (job.finished or report.finished) else 0,
                    1 if report.progressive else 0,
                    format_id,
                    report.content_type,
                    expires,
                    now,
                    job_id,
                    lease_id,
                ),
            ).rowcount
            # Conditional on the lease: under READ COMMITTED (PostgreSQL) another claim may have
            # taken the job since it was read; then nothing is written and the lease is lost.
            if updated != 1:
                raise LeaseLost()
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
        finalize: Finalizer | None = None,
    ) -> JobResult:
        now = self._now()
        with self._db.transaction() as conn:
            current = self._require(conn, job_id)
            if current.last_lease_id == lease_id and current.lease_id != lease_id:
                return self._repeated(current, _operation(state))
            job = self._leased(conn, job_id, lease_id, now)
            return self._release(
                conn,
                job,
                state=state,
                error_code=error_code,
                error_message=error_message,
                not_before=not_before,
                finalize=finalize,
                now=now,
            )

    def _release(  # noqa: PLR0913 - keyword-only fields of a release
        self,
        conn: Connection,
        job: Job,
        *,
        state: str,
        error_code: str | None,
        error_message: str | None,
        not_before: str | None,
        finalize: Finalizer | None,
        now: str,
    ) -> JobResult:
        sm.check_transition(job.state, state)
        if finalize is not None:
            finalize(conn, job)
        lease_id = job.lease_id
        result = JobResult(job.id, state, job.attempts, not_before if state == "queued" else None)
        outcome = json.dumps({"operation": _operation(state), **asdict(result)})
        keep = 1 if state == "ready" else 0
        updated = conn.execute(
            "UPDATE jobs SET state = ?, error_code = ?, error_message = ?, not_before = ?,"
            " lease_id = NULL, lease_owner = NULL, lease_expires_at = NULL,"
            " cancel_requested = 0, last_lease_id = ?, last_outcome = ?,"
            " progress = CASE WHEN ? = 1 THEN 1 ELSE progress END,"
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
                keep,
                None if state == "queued" else now,
                now,
                job.id,
                lease_id,
            ),
        ).rowcount
        if updated != 1:
            # Another claimer took the job since it was read: the whole release (and the
            # finalizer's writes) rolls back.
            raise LeaseLost()
        if state in ("failed", "cancelled"):
            self._fail_track(conn, job.track_id, now)
        return result

    def fail(
        self, job_id: str, lease_id: str, *, error_code: str, retryable: bool, message: str
    ) -> JobResult:
        moment = self._clock.now()
        now = format_ts(moment)
        with self._db.transaction() as conn:
            current = self._require(conn, job_id)
            if current.last_lease_id == lease_id and current.lease_id != lease_id:
                return self._repeated(current, "fail")
            job = self._leased(conn, job_id, lease_id, now)
            target = sm.failure_outcome(
                error_code,
                worker_says_retryable=retryable,
                attempts=job.attempts,
                max_attempts=job.max_attempts,
                cancel=bool(job.cancel_requested),
            )
            not_before = None
            if target == sm.JobState.QUEUED:
                delay = sm.retry_delay_s(job.attempts, self._rand)
                not_before = format_ts(moment + timedelta(seconds=delay))
            return self._release(
                conn,
                job,
                state=target.value,
                error_code="cancelled" if target == sm.JobState.CANCELLED else error_code,
                error_message=message,
                not_before=not_before,
                finalize=None,
                now=now,
            )

    def complete(self, job_id: str, lease_id: str, finalize: Finalizer) -> JobResult:
        return self.release(job_id, lease_id, state="ready", finalize=finalize)

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
