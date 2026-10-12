# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Worker side of the canary against the real api (in process, over an ASGI transport) with
the fake downloader: scheduled runs, the admin's "run the canary now", the result stored once
in `canary_runs`, and the downloaded file never kept. No network, no real download."""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from tests.canary.conftest import no_sleep
from ultimatetunes.app import create_app
from ultimatetunes.canary.checks import FAKE_VIDEO_ID
from ultimatetunes.canary.settings import CanarySettings
from ultimatetunes.canary.worker import CanaryState, CanaryWorker, build_canary_worker
from ultimatetunes.core.clock import FakeClock, format_ts
from ultimatetunes.core.services import Services, build_services
from ultimatetunes.db import Database
from ultimatetunes.errors import WorkerErrorCode
from ultimatetunes.settings import Settings
from ultimatetunes.worker.archiver import PendingArchiver
from ultimatetunes.worker.client import ApiUnavailableError, HttpWorkerApi
from ultimatetunes.worker.fake import FakeDownloader
from ultimatetunes.worker.loop import Worker
from ultimatetunes.worker.settings import WorkerSettings

pytestmark = pytest.mark.anyio
TOKEN = "worker-token-for-canary-tests-0123456789abcdef"


@dataclass
class Stack:
    services: Services
    db: Database
    clock: FakeClock
    client: httpx.AsyncClient
    state_file: Path

    def runs(self) -> list[dict[str, Any]]:
        with self.db.read() as conn:
            rows = conn.execute(
                "SELECT source, worker_id, ytdlp_version, ok, message FROM canary_runs"
                " ORDER BY ran_at"
            ).fetchall()
        return [dict(r) for r in rows]

    def request(self, command: str = "run_canary", command_id: str = "c1") -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO worker_commands (id, command, created_at) VALUES (?, ?, ?)",
                (command_id, command, format_ts(self.clock.now())),
            )


@pytest.fixture
async def stack(
    settings: Settings, db: Database, clock: FakeClock, tmp_path: Path
) -> AsyncIterator[Stack]:
    configured = settings.model_copy(
        update={"worker_token": SecretStr(TOKEN), "database_path": tmp_path / "data" / "ut.db"}
    )
    services = build_services(configured, clock)
    transport = httpx.ASGITransport(app=create_app(services=services))
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
        yield Stack(services, db, clock, client, tmp_path / "canary-state.json")
    services.db.close()


def make_worker(
    stack: Stack, downloader: Any = None, api: Any = None, **canary: Any
) -> CanaryWorker:
    knobs: dict[str, Any] = {"canary_first_delay_s": 0, "canary_state_file": stack.state_file}
    settings = CanarySettings(**(knobs | canary))
    return CanaryWorker(
        canary=settings,
        state=CanaryState(settings.canary_state_file),
        video_id=FAKE_VIDEO_ID,
        api=api or HttpWorkerApi(stack.client, TOKEN, retries=0),
        downloader=downloader or FakeDownloader(stack.services.staging, chunks=2, sleep=no_sleep),
        archiver=PendingArchiver(),
        staging=stack.services.staging,
        library=stack.services.library,
        settings=WorkerSettings(poll_interval_s=0.01),
        worker_id="w1",
        clock=stack.clock,
    )


def staged_files(stack: Stack) -> list[Path]:
    return [p for p in stack.services.settings.staging_dir.rglob("*") if p.is_file()]


async def test_the_first_housekeeping_runs_the_canary_and_reports_it(stack: Stack) -> None:
    worker = make_worker(stack)
    await worker.housekeeping()
    assert stack.runs() == [
        {"source": "worker", "worker_id": "w1", "ytdlp_version": "fake", "ok": 1, "message": None}
    ]
    assert staged_files(stack) == []
    assert list(stack.services.settings.music_dir.iterdir()) == []
    saved = json.loads(stack.state_file.read_text(encoding="utf-8"))
    assert saved == {"lastRun": "2026-10-12T08:00:00.000Z"}


async def test_the_canary_runs_daily_and_the_result_is_stored_once(stack: Stack) -> None:
    worker = make_worker(stack)
    await worker.housekeeping()
    stack.clock.advance(worker.settings.status_interval_s)
    await worker.housekeeping()  # a new report carries the same result: stored once
    assert len(stack.runs()) == 1
    stack.clock.advance(timedelta(hours=24).total_seconds())
    await worker.housekeeping()
    assert len(stack.runs()) == 2


async def test_the_first_run_waits_for_the_delay(stack: Stack) -> None:
    worker = make_worker(stack, canary_first_delay_s=600)
    await worker.housekeeping()
    assert stack.runs() == []
    stack.clock.advance(600)
    await worker.housekeeping()
    assert len(stack.runs()) == 1


async def test_a_restart_remembers_the_last_run(stack: Stack) -> None:
    await make_worker(stack).housekeeping()
    stack.clock.advance(3600)
    restarted = make_worker(stack)
    assert not restarted.canary_due()
    await restarted.housekeeping()
    assert len(stack.runs()) == 1


async def test_the_admin_can_run_it_now(stack: Stack) -> None:
    worker = make_worker(stack, canary_enabled=False)
    await worker.housekeeping()
    assert stack.runs() == []
    stack.clock.advance(1)
    stack.request()
    stack.clock.advance(worker.settings.status_interval_s)
    await worker.housekeeping()  # the report delivers run_canary: it runs at once
    await worker.housekeeping()  # and the next report carries the result
    assert [r["ok"] for r in stack.runs()] == [1]


async def test_a_failed_download_is_reported_as_a_failed_canary(stack: Stack) -> None:
    failing = FakeDownloader(
        stack.services.staging,
        chunks=4,
        sleep=no_sleep,
        fail_after_bytes=1,
        fail_code=WorkerErrorCode.EXTRACTOR_ERROR,
    )
    worker = make_worker(stack, downloader=failing)
    await worker.housekeeping()
    [run] = stack.runs()
    assert run["ok"] == 0
    assert run["message"] == "download: extractor_error: fake failure"
    assert staged_files(stack) == []


class Unreachable:
    """An api that never answers."""

    def __init__(self) -> None:
        self.reports = 0

    async def report_status(self, worker_id: str, **fields: Any) -> list[str]:
        self.reports += 1
        raise ApiUnavailableError("connection refused")


async def test_an_unreachable_api_only_logs(stack: Stack, caplog: pytest.LogCaptureFixture) -> None:
    api = Unreachable()
    worker = make_worker(stack, api=api)
    await worker.housekeeping()
    assert worker.last_report is not None
    assert worker.last_report.ok
    assert api.reports == 1
    assert "status report failed" in caplog.text


class Commands:
    def __init__(self, commands: list[str]) -> None:
        self.commands = commands
        self.canaries: list[Any] = []

    async def report_status(self, worker_id: str, **fields: Any) -> list[str]:
        self.canaries.append(fields["canary"])
        commands, self.commands = self.commands, []
        return commands


async def test_other_commands_still_work(stack: Stack, caplog: pytest.LogCaptureFixture) -> None:
    api = Commands(["update_ytdlp", "dance"])
    worker = make_worker(stack, api=api, canary_enabled=False)
    await worker.report_status()
    assert "unknown command dance ignored" in caplog.text
    assert api.canaries == [None]


def test_the_state_file_falls_back_to_memory(tmp_path: Path, clock: FakeClock) -> None:
    broken = tmp_path / "missing-dir" / "state.json"
    state = CanaryState(broken)
    assert state.last_run() is None
    state.save(clock.now())
    assert state.last_run() == clock.now()
    garbage = tmp_path / "garbage.json"
    garbage.write_text("{not json", encoding="utf-8")
    assert CanaryState(garbage).last_run() is None


def test_the_production_factory_wraps_the_t08_worker(settings: Settings, tmp_path: Path) -> None:
    client = httpx.AsyncClient(base_url="http://api")
    worker = build_canary_worker(
        settings.model_copy(update={"worker_token": SecretStr(TOKEN)}),
        WorkerSettings(),
        client,
    )
    assert isinstance(worker, Worker)
    assert isinstance(worker.downloader, FakeDownloader)
    assert worker.video_id == FAKE_VIDEO_ID
