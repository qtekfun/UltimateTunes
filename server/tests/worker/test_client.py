# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""HttpWorkerApi: request shapes, retries of idempotent calls, problems mapped to errors."""

import json
from typing import Any

import httpx
import pytest

from ultimatetunes.errors import (
    Conflict,
    InvalidStateTransition,
    InvalidWorkerToken,
    LeaseLost,
    TunesError,
)
from ultimatetunes.worker.client import (
    ApiUnavailableError,
    ClaimedJob,
    HttpWorkerApi,
    JobHints,
    NoJob,
    problem_error,
)
from ultimatetunes.worker.downloader import DownloadProgress

pytestmark = pytest.mark.anyio
JOB = ClaimedJob(
    job_id="j1",
    track_id="t1",
    video_id="Qx7Lm2pZ0aB",
    attempt=1,
    max_attempts=3,
    staging_dir="j1/1",
    hints=JobHints("Paper Moons", "The Paper Lanterns"),
    lease_id="l1",
    heartbeat_s=20,
)
LEASE = {"leaseId": "l1", "expiresAt": "2026-10-12T08:01:00.000Z", "cancelRequested": False}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class Api:
    """Records requests and answers from a queue of responses."""

    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []
        self.sleeps: list[float] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.responses.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def body(self, index: int = -1) -> Any:
        return json.loads(self.requests[index].content)

    def client(self, retries: int = 3) -> HttpWorkerApi:
        async def sleep(seconds: float) -> None:
            self.sleeps.append(seconds)

        http = httpx.AsyncClient(transport=httpx.MockTransport(self.handle), base_url="http://api")
        return HttpWorkerApi(http, "token-x", retries=retries, sleep=sleep)


def problem(status: int, code: str) -> httpx.Response:
    return httpx.Response(status, json={"code": code, "detail": f"{code} detail"})


async def test_claim_parses_the_job_and_sends_the_token() -> None:
    claimed = {
        "job": {
            "id": "j1",
            "kind": "download",
            "trackId": "t1",
            "videoId": "Qx7Lm2pZ0aB",
            "attempt": 2,
            "maxAttempts": 3,
            "priority": 100,
            "stagingDir": "j1/2",
            "hints": {"title": "Paper Moons", "artist": "The Paper Lanterns", "durationMs": 1},
        },
        "lease": {"leaseId": "l2", "expiresAt": "x", "heartbeatSeconds": 20},
    }
    api = Api(httpx.Response(200, json=claimed))
    job = await api.client().claim("w1", 60)
    assert isinstance(job, ClaimedJob)
    assert (job.job_id, job.attempt, job.staging_dir, job.lease_id) == ("j1", 2, "j1/2", "l2")
    assert job.hints == JobHints("Paper Moons", "The Paper Lanterns", duration_ms=1)
    assert api.requests[0].headers["authorization"] == "Bearer token-x"
    assert api.body() == {"workerId": "w1", "kinds": ["download"], "leaseSeconds": 60}


async def test_an_empty_queue_says_when_to_come_back() -> None:
    api = Api(
        httpx.Response(204, headers={"Retry-After": "3"}),
        httpx.Response(204, headers={"Retry-After": "soon"}),
        httpx.Response(204),
    )
    client = api.client()
    assert await client.claim("w1", 60) == NoJob(3.0)
    assert await client.claim("w1", 60) == NoJob(None)
    assert await client.claim("w1", 60) == NoJob(None)


async def test_a_long_poll_claim_asks_to_wait_and_reads_longer() -> None:
    api = Api(
        httpx.Response(204, headers={"Retry-After": "0"}),
        httpx.Response(204, headers={"Retry-After": "-1"}),
    )
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(api.handle), base_url="http://api", timeout=10.0
    )
    client = HttpWorkerApi(http, "token-x", claim_wait_s=8)
    assert await client.claim("w1", 60) == NoJob(0.0)  # waited: claim again at once
    assert api.body(0) == {
        "workerId": "w1",
        "kinds": ["download"],
        "leaseSeconds": 60,
        "waitSeconds": 8,
    }
    # The answer may take the whole wait: reading it gets that much more time.
    assert api.requests[0].extensions["timeout"]["read"] == 18.0
    assert api.requests[0].extensions["timeout"]["connect"] == 10.0
    assert await client.claim("w1", 60) == NoJob(None)


async def test_a_long_poll_without_a_read_timeout_keeps_none() -> None:
    api = Api(httpx.Response(204, headers={"Retry-After": "0"}))
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(api.handle),
        base_url="http://api",
        timeout=httpx.Timeout(10.0, read=None),
    )
    await HttpWorkerApi(http, "token-x", claim_wait_s=8).claim("w1", 60)
    assert api.requests[0].extensions["timeout"]["read"] is None


async def test_heartbeat_and_progress_bodies() -> None:
    api = Api(
        httpx.Response(200, json=LEASE),
        httpx.Response(200, json=LEASE | {"cancelRequested": True}),
        httpx.Response(200, json=LEASE),
        httpx.Response(200, json=LEASE),
    )
    client = api.client()
    assert not (await client.heartbeat(JOB, 45)).cancel_requested
    assert api.body() == {"leaseId": "l1", "leaseSeconds": 45}
    report = DownloadProgress(
        10, 40, "j1/1/a.webm.part", "j1/1/a.webm", False, "251", "audio/webm", True
    )
    assert (await client.progress(JOB, "downloading", report)).cancel_requested
    assert api.body() == {
        "leaseId": "l1",
        "state": "downloading",
        "progress": 0.25,
        "bytesDownloaded": 10,
        "expectedSize": 40,
        "partPath": "j1/1/a.webm.part",
        "finalPath": "j1/1/a.webm",
        "finished": False,
        "formatId": "251",
        "contentType": "audio/webm",
        "progressive": True,
    }
    unknown = DownloadProgress(10, None, "p", "f", False, "251", "audio/webm", True)
    await client.progress(JOB, "downloading", unknown)
    assert (api.body()["progress"], api.body()["expectedSize"]) == (0.0, None)
    done = DownloadProgress(40, None, "p", "f", True, "251", "audio/webm", True)
    await client.progress(JOB, "tagging", done)
    assert (api.body()["progress"], api.body()["state"]) == (1.0, "tagging")


async def test_complete_fail_register_replaygain_and_status() -> None:
    result = {"jobId": "j1", "state": "ready", "attempts": 1, "notBefore": None}
    api = Api(
        httpx.Response(200, json=result),
        httpx.Response(200, json=result | {"state": "queued", "notBefore": "t"}),
        httpx.Response(200, json={"merged": False}),
        httpx.Response(204),
        httpx.Response(200, json={"commands": ["update_ytdlp"]}),
    )
    client = api.client()
    done = await client.complete(
        JOB,
        track_id="t1",
        library_path="A/B/01 - C.opus",
        staging_path="j1/1/a.webm",
        staging_size=40,
    )
    assert done.state == "ready"
    assert api.body() == {
        "leaseId": "l1",
        "trackId": "t1",
        "libraryPath": "A/B/01 - C.opus",
        "staging": {"path": "j1/1/a.webm", "sizeBytes": 40, "sha256": None},
    }
    failed = await client.fail(JOB, error_code="network_error", retryable=True, message="x" * 3000)
    assert (failed.state, failed.not_before) == ("queued", "t")
    assert len(api.body()["message"]) == 2000
    assert await client.register_track({"jobId": "j1"}) == {"merged": False}
    assert api.requests[-1].url.path == "/internal/v1/library/tracks"
    await client.update_replay_gain("t9", {"jobId": "j1"})
    assert api.requests[-1].method == "PUT"
    assert api.requests[-1].url.path == "/internal/v1/library/tracks/t9/replaygain"
    commands = await client.report_status("w1", version="0.1.0", ytdlp_version="2026.08.19")
    assert commands == ["update_ytdlp"]
    assert api.body() == {"version": "0.1.0", "ytdlpVersion": "2026.08.19", "canary": None}


async def test_transport_errors_and_5xx_are_retried_with_backoff() -> None:
    request = httpx.Request("POST", "http://api")
    api = Api(
        httpx.ConnectError("refused", request=request),
        httpx.Response(503),
        httpx.Response(200, json=LEASE),
    )
    await api.client().heartbeat(JOB, 60)
    assert api.sleeps == [0.5, 1.0]
    down = Api(*(httpx.Response(500) for _ in range(3)))
    with pytest.raises(ApiUnavailableError, match="HTTP 500"):
        await down.client(retries=2).heartbeat(JOB, 60)
    assert len(down.requests) == 3


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (problem(409, "lease_lost"), LeaseLost),
        (problem(409, "invalid_state_transition"), InvalidStateTransition),
        (problem(401, "invalid_worker_token"), InvalidWorkerToken),
        (problem(409, "conflict"), Conflict),
        (problem(418, "teapot"), TunesError),
        (httpx.Response(400, content=b"not json"), TunesError),
        (httpx.Response(400, json=["a list"]), TunesError),
    ],
)
async def test_problems_become_typed_errors(
    response: httpx.Response, error: type[TunesError]
) -> None:
    api = Api(response)
    with pytest.raises(error) as caught:
        await api.client().heartbeat(JOB, 60)
    assert type(caught.value) is error
    assert len(api.requests) == 1


def test_problem_detail_is_kept() -> None:
    assert problem_error(problem(409, "lease_lost")).message == "lease_lost detail"
    assert problem_error(httpx.Response(400)).message == "api answered 400"


async def test_youtube_cookies_are_read_from_the_api_or_none() -> None:
    cookies = "# Netscape HTTP Cookie File\n"
    api = Api(
        httpx.Response(200, json={"youtubeCookies": cookies}),
        httpx.Response(204),
    )
    client = api.client()
    assert await client.youtube_cookies() == cookies
    assert api.requests[-1].method == "GET"
    assert api.requests[-1].url.path == "/internal/v1/youtube-cookies"
    assert await client.youtube_cookies() is None
