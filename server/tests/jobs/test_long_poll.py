# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Long-poll claims (issue #55): `JobSignal`, `claim_waiting` and `waitSeconds` over HTTP.

An idle worker used to wait up to `Retry-After` (2 s) before a new job even started: these tests
check that a held claim answers as soon as a job is queued, that it still finds jobs queued
behind its back (another replica, a backoff that ended) by polling, and that it ends with
`Retry-After: 0` after the wait. Waits are short real waits bounded by `fail_after`.
"""

import asyncio
import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import anyio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.types import Message, Scope

from tests.jobs.test_queue import add_track
from ultimatetunes.app import create_app
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.services import Services, build_services
from ultimatetunes.db import Database
from ultimatetunes.jobs.settings import JobsSettings
from ultimatetunes.jobs.signal import JobSignal, claim_waiting
from ultimatetunes.settings import Settings

pytestmark = pytest.mark.anyio

TOKEN = "worker-token-for-tests"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
VIDEO = "Rb8Tn3ZcYv0"
LONG = 30.0  # longer than any test may take: reaching it is a failure (fail_after)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class Attempts:
    """An `attempt` that finds nothing until `ready` is set, counting its calls."""

    def __init__(self) -> None:
        self.calls = 0
        self.ready = False
        self.called = anyio.Event()

    async def __call__(self) -> str | None:
        self.calls += 1
        self.called.set()
        return "job" if self.ready else None


async def test_a_job_found_at_once_is_returned_without_waiting() -> None:
    attempts = Attempts()
    attempts.ready = True
    with anyio.fail_after(1):
        found = await claim_waiting(attempts, JobSignal(), wait_s=LONG, poll_s=LONG)
    assert (found, attempts.calls) == ("job", 1)


async def test_without_a_wait_nothing_found_is_none_at_once() -> None:
    attempts = Attempts()
    found = await claim_waiting(attempts, JobSignal(), wait_s=0, poll_s=LONG)
    assert (found, attempts.calls) == (None, 1)


async def test_a_notify_from_another_thread_wakes_the_claim() -> None:
    signal = JobSignal()
    attempts = Attempts()

    def enqueue() -> None:  # e.g. a request handler in the threadpool
        attempts.ready = True
        signal.notify()

    async def later() -> None:
        await attempts.called.wait()
        await anyio.to_thread.run_sync(enqueue)

    with anyio.fail_after(5):  # far below poll_s: only the signal can wake it
        async with anyio.create_task_group() as tg:
            tg.start_soon(later)
            found = await claim_waiting(attempts, signal, wait_s=LONG, poll_s=LONG)
    assert (found, attempts.calls) == ("job", 2)


async def test_without_a_signal_the_queue_is_polled_until_the_wait_ends() -> None:
    attempts = Attempts()
    started = time.monotonic()
    with anyio.fail_after(5):
        found = await claim_waiting(attempts, JobSignal(), wait_s=0.2, poll_s=0.04)
    assert found is None
    assert attempts.calls >= 4  # once at the start, then about every poll_s
    assert time.monotonic() - started >= 0.2


async def test_a_job_queued_behind_its_back_is_found_by_polling() -> None:
    attempts = Attempts()

    async def elsewhere() -> None:  # another replica: no signal reaches this process
        await anyio.sleep(0.05)
        attempts.ready = True

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            tg.start_soon(elsewhere)
            found = await claim_waiting(attempts, JobSignal(), wait_s=LONG, poll_s=0.02)
    assert found == "job"


async def test_listeners_are_dropped_and_closed_loops_are_skipped() -> None:
    signal = JobSignal()
    with signal.listen() as event:
        signal.notify()
        await asyncio.sleep(0)  # call_soon_threadsafe runs on the next loop iteration
        assert event.is_set()
    assert not signal._waiters
    closed = asyncio.new_event_loop()
    closed.close()
    signal._waiters.add((closed, asyncio.Event()))
    signal.notify()  # no error: nobody waits on a closed loop


# ------------------------------------------------------------------ over HTTP


@pytest.fixture
def services(settings: Settings, db: Database, clock: FakeClock, tmp_path: Path) -> Services:
    configured = settings.model_copy(
        update={"worker_token": SecretStr(TOKEN), "database_path": tmp_path / "data" / "ut.db"}
    )
    return build_services(configured, clock)


def app_with(services: Services, **jobs: float) -> FastAPI:
    app = create_app(services=services)
    app.state.jobs_settings = JobsSettings(**jobs)  # type: ignore[arg-type]
    return app


@pytest.fixture
def client(services: Services) -> Iterator[TestClient]:
    with TestClient(app_with(services, claim_poll_s=LONG)) as test_client:
        yield test_client


def claim(client: TestClient, wait: int) -> Any:
    return client.post(
        "/internal/v1/jobs/claim",
        json={"workerId": "w1", "leaseSeconds": 30, "waitSeconds": wait},
        headers=AUTH,
    )


def test_a_held_claim_answers_as_soon_as_a_job_is_queued(
    client: TestClient, services: Services, db: Database, clock: FakeClock
) -> None:
    add_track(db, clock, "t1", VIDEO)
    answers: list[Any] = []
    holder = threading.Thread(target=lambda: answers.append(claim(client, 25)))
    started = time.monotonic()
    holder.start()
    time.sleep(0.2)  # the claim is waiting by now (poll_s is LONG: only the signal wakes it)
    job = services.jobs.enqueue(track_id="t1", video_id=VIDEO, priority=100)
    holder.join(timeout=10)
    assert not holder.is_alive()
    assert time.monotonic() - started < 5
    assert answers[0].status_code == 200
    assert answers[0].json()["job"]["id"] == job.id


def test_a_held_claim_that_finds_nothing_says_call_again_at_once(services: Services) -> None:
    with TestClient(app_with(services, claim_max_wait_s=0.1, claim_poll_s=0.02)) as client:
        r = claim(client, 25)  # capped by the server
    assert r.status_code == 204
    assert r.headers["retry-after"] == "0"


def test_long_poll_off_on_the_server_answers_at_once(services: Services) -> None:
    with TestClient(app_with(services, claim_max_wait_s=0, claim_poll_s=LONG)) as client:
        started = time.monotonic()
        r = claim(client, 25)
    assert time.monotonic() - started < 5
    assert r.status_code == 204
    assert r.headers["retry-after"] == "2"


def test_the_wait_is_validated(client: TestClient) -> None:
    assert claim(client, 31).status_code == 400
    assert claim(client, -1).status_code == 400


async def test_a_worker_that_hung_up_is_handed_no_job(
    services: Services, db: Database, clock: FakeClock
) -> None:
    add_track(db, clock, "t1", VIDEO)
    job = services.jobs.enqueue(track_id="t1", video_id=VIDEO, priority=100)
    app = app_with(services, claim_poll_s=LONG)
    body = json.dumps({"workerId": "w1", "waitSeconds": 0}).encode()
    messages: list[Message] = [
        {"type": "http.request", "body": body, "more_body": False},
        {"type": "http.disconnect"},
    ]
    sent: list[Message] = []

    async def receive() -> Message:
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        sent.append(message)

    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/internal/v1/jobs/claim",
        "raw_path": b"/internal/v1/jobs/claim",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"authorization", f"Bearer {TOKEN}".encode()),
            (b"content-type", b"application/json"),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("api", 8044),
    }
    try:
        await app(scope, receive, send)  # no lifespan: the database is closed below
    finally:
        services.db.close()
    assert sent[0]["status"] == 204
    with db.read() as conn:
        state = conn.execute("SELECT state FROM jobs WHERE id = ?", (job.id,)).scalar()
    assert state == "queued"
