# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Internal worker API, jobs and worker status (`/internal/v1/jobs`, `/internal/v1/workers`).
Owner: PLAN T08. Contract: contracts/openapi/internal-worker.yaml.

The worker token is checked before (`internal_api.py`). Handlers are thin: the queue
(`queue.py`) and the state machine (`state.py`) decide; errors are `TunesError`s rendered as
problems by the app.
"""

from functools import partial
from typing import Annotated, Literal

from fastapi import APIRouter, Path, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.alias_generators import to_camel
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response

from ultimatetunes.core.clock import format_ts
from ultimatetunes.core.services import services
from ultimatetunes.errors import InvalidParameter
from ultimatetunes.jobs.archive import archive_finalizer
from ultimatetunes.jobs.queue import Claimed, JobResult, Lease, ProgressReport
from ultimatetunes.jobs.settings import JobsSettings
from ultimatetunes.jobs.signal import claim_waiting
from ultimatetunes.jobs.workers import CanaryResult, WorkerRegistry

router = APIRouter()

JobId = Annotated[str, Path(alias="jobId")]
WorkerId = Annotated[str, Path(alias="workerId")]
MAX_ID = 64
MAX_WORKER_ID = 100
LeaseSeconds = Annotated[int, Field(ge=15, le=300)]
StagingPath = Annotated[str, Field(min_length=1, max_length=1024)]
FailCode = Literal[
    "video_unavailable",
    "format_unavailable",
    "extractor_error",
    "network_error",
    "rate_limited_upstream",
    "tagging_failed",
    "storage_error",
    "invalid_video_id",
    "cancelled",
    "internal_error",
]


class _Body(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)


class ClaimBody(_Body):
    worker_id: str = Field(min_length=1, max_length=100)
    kinds: list[Literal["download"]] = Field(default=["download"])
    lease_seconds: LeaseSeconds = 60
    wait_seconds: int = Field(default=0, ge=0, le=30)


class HeartbeatBody(_Body):
    lease_id: str
    lease_seconds: LeaseSeconds = 60


class ProgressBody(_Body):
    lease_id: str
    state: Literal["downloading", "tagging"]
    progress: float = Field(ge=0, le=1)
    bytes_downloaded: int = Field(ge=0)
    expected_size: int | None = Field(ge=1)
    part_path: StagingPath
    final_path: StagingPath
    finished: bool
    format_id: str = Field(min_length=1, max_length=32)
    content_type: str = Field(min_length=1, max_length=100)
    progressive: bool


class StagingFile(_Body):
    path: StagingPath
    size_bytes: int = Field(ge=0)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class CompleteBody(_Body):
    lease_id: str
    track_id: str = Field(min_length=1, max_length=64)
    library_path: str | None = Field(min_length=1, max_length=1024)
    staging: StagingFile


class FailBody(_Body):
    lease_id: str
    error_code: FailCode
    retryable: bool
    message: str = Field(max_length=2000)


class Canary(_Body):
    at: str = Field(min_length=1, max_length=40)
    ok: bool
    message: str | None = Field(default=None, max_length=2000)


class WorkerStatusBody(_Body):
    version: str = Field(max_length=100)
    ytdlp_version: str = Field(max_length=100)
    canary: Canary | None = None


def _lease(lease: Lease) -> dict[str, object]:
    return {
        "leaseId": lease.lease_id,
        "expiresAt": lease.expires_at,
        "cancelRequested": lease.cancel_requested,
    }


def _result(result: JobResult) -> dict[str, object]:
    return {
        "jobId": result.job_id,
        "state": result.state,
        "attempts": result.attempts,
        "notBefore": result.not_before,
    }


def _claimed(request: Request, claimed: Claimed) -> dict[str, object]:
    job = claimed.job
    hints = services(request).jobs.hints(job)
    return {
        "job": {
            "id": job.id,
            "kind": job.kind,
            "trackId": job.track_id,
            "videoId": job.yt_video_id,
            "attempt": job.attempts,
            "maxAttempts": job.max_attempts,
            "priority": job.priority,
            "stagingDir": job.staging_dir,
            "hints": {
                "title": hints.title,
                "artist": hints.artist_name,
                "album": hints.album_name,
                "albumBrowseId": hints.yt_album_browse_id,
                "artistChannelId": hints.yt_artist_channel_id,
                "durationMs": hints.duration_ms,
                "year": hints.year,
                "trackNumber": hints.track_number,
                "thumbnailUrl": hints.yt_thumbnail_url,
            },
        },
        "lease": {
            "leaseId": claimed.lease.lease_id,
            "expiresAt": claimed.lease.expires_at,
            "heartbeatSeconds": claimed.lease.heartbeat_s,
        },
    }


def _settings(request: Request) -> JobsSettings:
    found = getattr(request.app.state, "jobs_settings", None)
    return found if isinstance(found, JobsSettings) else JobsSettings()


async def _body[M: BaseModel](request: Request, model: type[M]) -> M:
    """The JSON body, validated only now: the router's token check has already run, so a
    caller without the token learns nothing about the bodies (always the same 401)."""
    raw = await request.body()
    try:
        return model.model_validate_json(raw or b"null")
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in e["loc"]) or "body" for e in exc.errors()})
        raise InvalidParameter(f"Invalid: {', '.join(fields)}") from exc


def _job_id(job_id: str) -> str:
    # Unknown ids are simply not found; only absurd lengths are refused up front.
    if len(job_id) > MAX_ID:
        raise InvalidParameter("Invalid: jobId")
    return job_id


@router.post("/internal/v1/jobs/claim")
async def claim_job(request: Request) -> Response:
    body = await _body(request, ClaimBody)
    settings = _settings(request)
    jobs = services(request).jobs
    claim = partial(
        jobs.claim,
        body.worker_id,
        lease_s=body.lease_seconds,
        kinds=tuple(dict.fromkeys(body.kinds)),
    )

    async def attempt() -> Claimed | None:
        # A worker that hung up (e.g. it is stopping) must not be handed a job it never sees.
        if await request.is_disconnected():
            return None
        return await run_in_threadpool(claim)

    wait_s = min(float(body.wait_seconds), settings.claim_max_wait_s)
    claimed = await claim_waiting(attempt, jobs.signal, wait_s=wait_s, poll_s=settings.claim_poll_s)
    if claimed is None:
        # After a long poll the worker asks again at once; otherwise it waits a little.
        retry = "0" if wait_s > 0 else str(settings.claim_retry_after_s)
        return Response(status_code=204, headers={"Retry-After": retry})
    return JSONResponse(_claimed(request, claimed))


@router.post("/internal/v1/jobs/{jobId}/heartbeat")
async def heartbeat(request: Request, job_id: JobId) -> Response:
    body = await _body(request, HeartbeatBody)
    jobs = services(request).jobs
    lease = await run_in_threadpool(
        jobs.heartbeat, _job_id(job_id), body.lease_id, lease_s=body.lease_seconds
    )
    return JSONResponse(_lease(lease))


@router.post("/internal/v1/jobs/{jobId}/progress")
async def report_progress(request: Request, job_id: JobId) -> Response:
    body = await _body(request, ProgressBody)
    report = ProgressReport(
        state=body.state,
        progress=body.progress,
        bytes_downloaded=body.bytes_downloaded,
        expected_size=body.expected_size,
        part_path=body.part_path,
        final_path=body.final_path,
        finished=body.finished,
        format_id=body.format_id,
        content_type=body.content_type,
        progressive=body.progressive,
    )
    jobs = services(request).jobs
    lease = await run_in_threadpool(jobs.progress, _job_id(job_id), body.lease_id, report)
    return JSONResponse(_lease(lease))


@router.post("/internal/v1/jobs/{jobId}/complete")
async def complete_job(request: Request, job_id: JobId) -> Response:
    body = await _body(request, CompleteBody)
    svc = services(request)
    finalize = archive_finalizer(
        svc.library,
        track_id=body.track_id,
        library_path=body.library_path,
        now=format_ts(svc.clock.now()),
    )
    result = await run_in_threadpool(svc.jobs.complete, _job_id(job_id), body.lease_id, finalize)
    return JSONResponse(_result(result))


@router.post("/internal/v1/jobs/{jobId}/fail")
async def fail_job(request: Request, job_id: JobId) -> Response:
    body = await _body(request, FailBody)
    result = await run_in_threadpool(
        partial(
            services(request).jobs.fail,
            _job_id(job_id),
            body.lease_id,
            error_code=body.error_code,
            retryable=body.retryable,
            message=body.message,
        )
    )
    return JSONResponse(_result(result))


@router.put("/internal/v1/workers/{workerId}/status")
async def report_worker_status(request: Request, worker_id: WorkerId) -> Response:
    body = await _body(request, WorkerStatusBody)
    if len(worker_id) > MAX_WORKER_ID:
        raise InvalidParameter("Invalid: workerId")
    svc = services(request)
    canary = (
        None
        if body.canary is None
        else CanaryResult(body.canary.at, body.canary.ok, body.canary.message)
    )
    commands = await run_in_threadpool(
        partial(
            WorkerRegistry(svc.db, svc.clock).report,
            worker_id,
            version=body.version,
            ytdlp_version=body.ytdlp_version,
            canary=canary,
        )
    )
    return JSONResponse({"commands": commands})
