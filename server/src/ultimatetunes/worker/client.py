# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`WorkerApi`: the worker's side of the internal worker API (contracts/openapi/
internal-worker.yaml). The worker has no database access; this client is all it has.

Every call is idempotent per the contract, so transport errors and 5xx answers are retried a
few times with a short backoff before `ApiUnavailableError` is raised. Problems map back to the
typed errors of `errors.py` (`LeaseLost`, `InvalidStateTransition`, ...), so the loop reacts
to `lease_lost` by dropping the job. The bearer token never reaches a log line.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

import anyio
import httpx

from ultimatetunes.errors import (
    Conflict,
    InvalidParameter,
    InvalidStateTransition,
    InvalidWorkerToken,
    LeaseLost,
    NotFound,
    PathRejected,
    TunesError,
)
from ultimatetunes.worker.downloader import DownloadProgress

log = logging.getLogger(__name__)

_PROBLEMS: dict[str, type[TunesError]] = {
    "lease_lost": LeaseLost,
    "invalid_state_transition": InvalidStateTransition,
    "not_found": NotFound,
    "path_rejected": PathRejected,
    "invalid_worker_token": InvalidWorkerToken,
    "conflict": Conflict,
    "invalid_parameter": InvalidParameter,
}
SERVER_ERROR = 500


class ApiUnavailableError(Exception):
    """The api did not answer usefully after the retries (transport error or 5xx)."""


@dataclass(frozen=True)
class JobHints:
    title: str
    artist: str
    album: str | None = None
    album_browse_id: str | None = None
    artist_channel_id: str | None = None
    duration_ms: int | None = None
    year: int | None = None
    track_number: int | None = None
    thumbnail_url: str | None = None


@dataclass(frozen=True)
class ClaimedJob:
    job_id: str
    track_id: str
    video_id: str
    attempt: int
    max_attempts: int
    staging_dir: str
    hints: JobHints
    lease_id: str
    heartbeat_s: int


@dataclass(frozen=True)
class NoJob:
    retry_after_s: float


@dataclass(frozen=True)
class LeaseInfo:
    expires_at: str
    cancel_requested: bool


@dataclass(frozen=True)
class JobOutcome:
    state: str
    attempts: int
    not_before: str | None


class WorkerApi(Protocol):
    async def claim(self, worker_id: str, lease_s: int) -> ClaimedJob | NoJob: ...

    async def heartbeat(self, job: ClaimedJob, lease_s: int) -> LeaseInfo: ...

    async def progress(
        self, job: ClaimedJob, state: str, report: DownloadProgress
    ) -> LeaseInfo: ...

    async def complete(
        self,
        job: ClaimedJob,
        *,
        track_id: str,
        library_path: str | None,
        staging_path: str,
        staging_size: int,
    ) -> JobOutcome: ...

    async def fail(
        self, job: ClaimedJob, *, error_code: str, retryable: bool, message: str
    ) -> JobOutcome: ...

    async def register_track(self, body: dict[str, Any]) -> dict[str, Any]:
        """`registerTrack` (T09 builds the body from the contract's `RegisterTrack`)."""
        ...

    async def update_replay_gain(self, track_id: str, body: dict[str, Any]) -> None: ...

    async def report_status(
        self,
        worker_id: str,
        *,
        version: str,
        ytdlp_version: str,
        canary: dict[str, Any] | None = None,
    ) -> list[str]: ...


def _hints(raw: dict[str, Any]) -> JobHints:
    return JobHints(
        title=str(raw.get("title", "")),
        artist=str(raw.get("artist", "")),
        album=raw.get("album"),
        album_browse_id=raw.get("albumBrowseId"),
        artist_channel_id=raw.get("artistChannelId"),
        duration_ms=raw.get("durationMs"),
        year=raw.get("year"),
        track_number=raw.get("trackNumber"),
        thumbnail_url=raw.get("thumbnailUrl"),
    )


def _outcome(raw: dict[str, Any]) -> JobOutcome:
    return JobOutcome(str(raw["state"]), int(raw["attempts"]), raw.get("notBefore"))


def _lease(raw: dict[str, Any]) -> LeaseInfo:
    return LeaseInfo(str(raw["expiresAt"]), bool(raw["cancelRequested"]))


def problem_error(response: httpx.Response) -> TunesError:
    """The typed error of a problem answer (unknown codes become `TunesError`)."""
    try:
        body = response.json()
    except ValueError:
        body = {}
    code = body.get("code") if isinstance(body, dict) else None
    detail = body.get("detail") if isinstance(body, dict) else None
    cls = _PROBLEMS.get(str(code), TunesError)
    return cls(str(detail or f"api answered {response.status_code}"))


class HttpWorkerApi:
    """`WorkerApi` over httpx. Pass `client` to reuse one (tests use an ASGI transport)."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        token: str,
        *,
        retries: int = 3,
        sleep: Callable[[float], Awaitable[None]] = anyio.sleep,
    ) -> None:
        self._client = client
        self._headers = {"Authorization": f"Bearer {token}"}
        self._retries = retries
        self._sleep = sleep

    async def _call(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> httpx.Response:
        delay = 0.5
        for attempt in range(self._retries + 1):
            try:
                response = await self._client.request(
                    method, path, json=body, headers=self._headers
                )
            except httpx.TransportError as exc:
                failure = f"{type(exc).__name__}"
            else:
                if response.status_code < SERVER_ERROR:
                    if response.is_error:
                        raise problem_error(response)
                    return response
                failure = f"HTTP {response.status_code}"
            if attempt < self._retries:
                log.warning("worker api %s %s failed (%s), retrying", method, path, failure)
                await self._sleep(delay)
                delay *= 2
        raise ApiUnavailableError(f"{method} {path}: {failure}")

    async def claim(self, worker_id: str, lease_s: int) -> ClaimedJob | NoJob:
        response = await self._call(
            "POST",
            "/internal/v1/jobs/claim",
            {"workerId": worker_id, "kinds": ["download"], "leaseSeconds": lease_s},
        )
        if response.status_code == httpx.codes.NO_CONTENT:
            try:
                retry = float(response.headers.get("retry-after", "0"))
            except ValueError:
                retry = 0.0
            return NoJob(retry)
        raw = response.json()
        job, lease = raw["job"], raw["lease"]
        return ClaimedJob(
            job_id=str(job["id"]),
            track_id=str(job["trackId"]),
            video_id=str(job["videoId"]),
            attempt=int(job["attempt"]),
            max_attempts=int(job["maxAttempts"]),
            staging_dir=str(job["stagingDir"]),
            hints=_hints(job.get("hints") or {}),
            lease_id=str(lease["leaseId"]),
            heartbeat_s=int(lease["heartbeatSeconds"]),
        )

    async def heartbeat(self, job: ClaimedJob, lease_s: int) -> LeaseInfo:
        response = await self._call(
            "POST",
            f"/internal/v1/jobs/{job.job_id}/heartbeat",
            {"leaseId": job.lease_id, "leaseSeconds": lease_s},
        )
        return _lease(response.json())

    async def progress(self, job: ClaimedJob, state: str, report: DownloadProgress) -> LeaseInfo:
        expected = report.expected_size
        fraction = min(1.0, report.downloaded_bytes / expected) if expected else 0.0
        if report.finished:
            fraction = 1.0
        response = await self._call(
            "POST",
            f"/internal/v1/jobs/{job.job_id}/progress",
            {
                "leaseId": job.lease_id,
                "state": state,
                "progress": fraction,
                "bytesDownloaded": report.downloaded_bytes,
                "expectedSize": expected,
                "partPath": report.part_path,
                "finalPath": report.final_path,
                "finished": report.finished,
                "formatId": report.format_id,
                "contentType": report.content_type,
                "progressive": report.progressive,
            },
        )
        return _lease(response.json())

    async def complete(
        self,
        job: ClaimedJob,
        *,
        track_id: str,
        library_path: str | None,
        staging_path: str,
        staging_size: int,
    ) -> JobOutcome:
        response = await self._call(
            "POST",
            f"/internal/v1/jobs/{job.job_id}/complete",
            {
                "leaseId": job.lease_id,
                "trackId": track_id,
                "libraryPath": library_path,
                "staging": {"path": staging_path, "sizeBytes": staging_size, "sha256": None},
            },
        )
        return _outcome(response.json())

    async def fail(
        self, job: ClaimedJob, *, error_code: str, retryable: bool, message: str
    ) -> JobOutcome:
        response = await self._call(
            "POST",
            f"/internal/v1/jobs/{job.job_id}/fail",
            {
                "leaseId": job.lease_id,
                "errorCode": error_code,
                "retryable": retryable,
                "message": message[:2000],
            },
        )
        return _outcome(response.json())

    async def register_track(self, body: dict[str, Any]) -> dict[str, Any]:
        response = await self._call("POST", "/internal/v1/library/tracks", body)
        found: dict[str, Any] = response.json()
        return found

    async def update_replay_gain(self, track_id: str, body: dict[str, Any]) -> None:
        await self._call("PUT", f"/internal/v1/library/tracks/{track_id}/replaygain", body)

    async def report_status(
        self,
        worker_id: str,
        *,
        version: str,
        ytdlp_version: str,
        canary: dict[str, Any] | None = None,
    ) -> list[str]:
        response = await self._call(
            "PUT",
            f"/internal/v1/workers/{worker_id}/status",
            {"version": version, "ytdlpVersion": ytdlp_version, "canary": canary},
        )
        commands = response.json().get("commands", [])
        return [str(c) for c in commands]
