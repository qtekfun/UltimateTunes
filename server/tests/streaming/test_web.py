# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The streaming area's app hook: the seam it installs, the report middleware and the
periodic staging sweep."""

import anyio
import pytest
from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from tests.streaming.harness import TOKEN, Live
from ultimatetunes.app import create_app
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.services import build_services
from ultimatetunes.settings import Settings
from ultimatetunes.streaming import web
from ultimatetunes.streaming.cleanup import StagingJanitor
from ultimatetunes.streaming.service import StreamingWhileDownloading
from ultimatetunes.streaming.watch import JobWatch

pytestmark = pytest.mark.anyio


async def test_the_seam_and_the_janitor_are_installed(live: Live) -> None:
    assert isinstance(live.client_app.state.pending_streams, StreamingWhileDownloading)
    assert isinstance(live.client_app.state.staging_janitor, StagingJanitor)


class Recorder:
    """A janitor and a watch that remember what the middleware asked."""

    def __init__(self) -> None:
        self.nudged: list[str] = []
        self.cleaned: list[str] = []
        self.watched: set[str] = set()
        self.fail = False

    def nudge(self, job_id: str) -> None:
        self.nudged.append(job_id)

    def watching(self, job_id: str) -> bool:
        return job_id in self.watched

    def clean_job(self, job_id: str) -> int:
        if self.fail:
            raise RuntimeError("database is locked")
        self.cleaned.append(job_id)
        return 1


def endpoint(status: int):  # type: ignore[no-untyped-def]
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    return app


async def receive_nothing() -> Message:
    return {"type": "lifespan.startup"}


async def send_nothing(message: Message) -> None:
    return None


async def call(app: web.ReportListener, method: str, path: str) -> list[Message]:
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    await app({"type": "http", "method": method, "path": path}, receive, send)
    return sent


async def test_reports_wake_listeners_and_clean_finished_jobs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rec = Recorder()
    ok = web.ReportListener(endpoint(200), watch=rec, janitor=rec)  # type: ignore[arg-type]
    await call(ok, "POST", "/internal/v1/jobs/j1/progress")
    await call(ok, "POST", "/internal/v1/jobs/j1/complete")
    rec.watched.add("j2")
    await call(ok, "POST", "/internal/v1/jobs/j2/fail")  # its listeners clean up after themselves
    assert rec.nudged == ["j1", "j1", "j2"]
    assert rec.cleaned == ["j1"]
    # Other requests pass through untouched.
    sent = await call(ok, "GET", "/internal/v1/jobs/j3/progress")
    assert sent[0]["status"] == 200
    await call(ok, "POST", "/rest/stream")
    seen: list[str] = []

    async def lifespan(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["type"])

    passthrough = web.ReportListener(lifespan, watch=rec, janitor=rec)  # type: ignore[arg-type]
    await passthrough({"type": "lifespan"}, receive_nothing, send_nothing)
    assert seen == ["lifespan"]
    assert rec.nudged == ["j1", "j1", "j2"]
    # A refused report (bad token, lost lease) changes nothing.
    refused = web.ReportListener(endpoint(409), watch=rec, janitor=rec)  # type: ignore[arg-type]
    await call(refused, "POST", "/internal/v1/jobs/j4/complete")
    assert "j4" not in rec.nudged
    # A failing cleanup is logged, never raised to the worker.
    rec.fail = True
    await call(ok, "POST", "/internal/v1/jobs/j5/fail")
    assert "staging cleanup of job j5 failed" in caplog.text


async def test_the_sweep_survives_a_failure(caplog: pytest.LogCaptureFixture) -> None:
    calls = 0

    class Flaky:
        def sweep(self) -> int:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("disk gone")
            return 0

    with anyio.move_on_after(0.3):
        await web.sweep_forever(Flaky(), 0.01)  # type: ignore[arg-type]
    assert calls > 1
    assert "staging sweep failed" in caplog.text


def test_the_lifespan_sweeps_staging(
    stream_settings: Settings, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UT_STAGING_SWEEP_INTERVAL_S", "60")
    orphan = stream_settings.staging_dir / "0199d6a2-4c1e-7b3a-9f10-2a6c8e019999" / "1" / "a.webm"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"x")
    services = build_services(stream_settings.model_copy(update={"worker_token": TOKEN}), clock)
    app = create_app(services=services)
    with TestClient(app):
        for _ in range(500):
            if not orphan.parent.parent.exists():
                break
            anyio.run(anyio.sleep, 0.01)
    assert not orphan.parent.parent.exists()


def test_watch_reads_through_the_queue(stream_settings: Settings, clock: FakeClock) -> None:
    services = build_services(stream_settings, clock)
    try:
        app = create_app(services=services)
        streams = app.state.pending_streams
        assert isinstance(streams, StreamingWhileDownloading)
        assert isinstance(streams._watch, JobWatch)
    finally:
        services.db.close()
