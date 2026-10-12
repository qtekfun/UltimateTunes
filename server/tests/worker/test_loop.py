# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The worker loop against the real api (in process, over an ASGI transport) with fake
downloaders: success, failures and retries, cancel, lost leases, a killed worker, shutdown,
the circuit breaker, yt-dlp updates and status reports. No network, no real download."""

import signal
import threading
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Any

import anyio
import anyio.lowlevel
import httpx
import pytest
from pydantic import SecretStr

from tests.jobs.test_queue import add_track
from ultimatetunes.app import create_app
from ultimatetunes.commands import CommandRegistry
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.services import Services, build_services
from ultimatetunes.core.storage import LocalLibraryStore, LocalStagingStore
from ultimatetunes.db import Database
from ultimatetunes.errors import Conflict, WorkerErrorCode
from ultimatetunes.settings import Settings
from ultimatetunes.worker import cli as worker_cli
from ultimatetunes.worker import loop
from ultimatetunes.worker.archiver import Archived, ArchiveRequest, PendingArchiver
from ultimatetunes.worker.client import ApiUnavailableError, ClaimedJob, HttpWorkerApi, NoJob
from ultimatetunes.worker.downloader import (
    Downloader,
    DownloadError,
    DownloadProgress,
    DownloadResult,
    ProgressCallback,
)
from ultimatetunes.worker.fake import FakeDownloader
from ultimatetunes.worker.loop import Worker, build_worker, run_worker
from ultimatetunes.worker.settings import WorkerSettings
from ultimatetunes.worker.ytdlp import YtDlpDownloader
from ultimatetunes.worker.ytdlp_runtime import UpdateError, UpdateResult

pytestmark = pytest.mark.anyio
TOKEN = "worker-token-for-tests"
VIDEO = "Rb8Tn3ZcYv0"
Handler = Callable[[int, FrameType | None], None]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@dataclass
class Stack:
    services: Services
    db: Database
    clock: FakeClock
    client: httpx.AsyncClient

    def job(self, job_id: str) -> Any:
        found = self.services.jobs.get(job_id)
        assert found is not None
        return found

    def track_status(self, track_id: str = "t1") -> object:
        with self.db.read() as conn:
            return conn.execute("SELECT status FROM tracks WHERE id = ?", (track_id,)).scalar()


@pytest.fixture
async def stack(
    settings: Settings, db: Database, clock: FakeClock, tmp_path: Path
) -> AsyncIterator[Stack]:
    configured = settings.model_copy(
        update={"worker_token": SecretStr(TOKEN), "database_path": tmp_path / "data" / "ut.db"}
    )
    services = build_services(configured, clock)
    app = create_app(services=services)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
        yield Stack(services, db, clock, client)
    services.db.close()


def enqueue(stack: Stack, track_id: str = "t1", video_id: str = VIDEO) -> str:
    add_track(stack.db, stack.clock, track_id, video_id)
    return stack.services.jobs.enqueue(track_id=track_id, video_id=video_id, priority=100).id


async def fast_sleep(seconds: float) -> None:
    """Heartbeats every few milliseconds instead of every few seconds."""
    await anyio.sleep(seconds / 1000)


async def no_sleep(_seconds: float) -> None:
    await anyio.lowlevel.checkpoint()


class Registering:
    """Stands in for T09: 'registers' the download (as the library endpoint would) and moves
    it into the library, then hands `complete` the reserved path."""

    def __init__(self, stack: Stack) -> None:
        self.stack = stack
        self.requests: list[ArchiveRequest] = []

    async def archive(self, request: ArchiveRequest) -> Archived:
        self.requests.append(request)
        path = f"The Paper Lanterns/Lanterns at Dusk/{request.job.video_id}.opus"
        size = request.staging.size(request.download.final_path)
        with self.stack.db.transaction() as conn:
            conn.execute(
                "UPDATE tracks SET size_bytes = ? WHERE id = ?", (size, request.job.track_id)
            )
            conn.execute(
                "UPDATE jobs SET library_path = ? WHERE id = ?", (path, request.job.job_id)
            )
        request.library.import_file(request.staging, request.download.final_path, path)
        return Archived(request.job.track_id, path)


class Stuck:
    """Writes a little, reports it, then hangs until cancelled."""

    def __init__(self, stack: Stack) -> None:
        self.stack = stack
        self.started = anyio.Event()

    async def download(
        self, video_id: str, job_dir: str, on_progress: ProgressCallback
    ) -> DownloadResult:
        part = f"{job_dir}/{video_id}.opus.part"
        with self.stack.services.staging.open_write(part) as out:
            out.write(b"x" * 10)
        await on_progress(
            DownloadProgress(10, 100, part, part[:-5], False, "fake-opus", "audio/ogg", True)
        )
        self.started.set()
        await anyio.sleep_forever()
        raise AssertionError("never reached")


class Raising:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    async def download(
        self, video_id: str, job_dir: str, on_progress: ProgressCallback
    ) -> DownloadResult:
        raise self.error


class Silent:
    """Downloads without a single progress report."""

    def __init__(self, stack: Stack) -> None:
        self.stack = stack

    async def download(
        self, video_id: str, job_dir: str, on_progress: ProgressCallback
    ) -> DownloadResult:
        final = f"{job_dir}/{video_id}.opus"
        with self.stack.services.staging.open_write(final) as out:
            out.write(b"OggS" * 8)
        return DownloadResult(final, "fake-opus", "opus", "audio/ogg", 32, 1000)


class Flaky(HttpWorkerApi):
    """The real client, with chosen calls failing a given number of times."""

    def __init__(self, client: httpx.AsyncClient, failures: dict[str, int]) -> None:
        super().__init__(client, TOKEN, retries=0)
        self.failures = failures

    def _maybe_fail(self, name: str) -> None:
        if self.failures.get(name, 0) > 0:
            self.failures[name] -= 1
            raise ApiUnavailableError(f"{name} down")

    async def progress(self, job: ClaimedJob, state: str, report: DownloadProgress) -> Any:
        self._maybe_fail("progress")
        return await super().progress(job, state, report)

    async def heartbeat(self, job: ClaimedJob, lease_s: int) -> Any:
        self._maybe_fail("heartbeat")
        return await super().heartbeat(job, lease_s)

    async def fail(self, job: ClaimedJob, **fields: Any) -> Any:
        self._maybe_fail("fail")
        return await super().fail(job, **fields)

    async def claim(self, worker_id: str, lease_s: int) -> Any:
        self._maybe_fail("claim")
        return await super().claim(worker_id, lease_s)

    async def report_status(self, worker_id: str, **fields: Any) -> list[str]:
        self._maybe_fail("report_status")
        return await super().report_status(worker_id, **fields)


class FakeRuntime:
    def __init__(self, *, fail_update: bool = False, fail_install: bool = False) -> None:
        self.updates = 0
        self.installs = 0
        self.fail_update = fail_update
        self.fail_install = fail_install
        self.version: str | None = "2026.08.19"

    def current_version(self) -> str | None:
        return self.version

    async def ensure_installed(self) -> str:
        self.installs += 1
        if self.fail_install:
            raise UpdateError("no seed")
        return "2026.08.19"

    async def update(self, *, force: bool = False) -> UpdateResult:
        self.updates += 1
        if self.fail_update:
            raise UpdateError("GitHub down")
        return UpdateResult("2026.09.28", updated=self.updates == 1)


def make_worker(  # noqa: PLR0913 - test knobs
    stack: Stack,
    downloader: Downloader,
    *,
    archiver: Any = None,
    api: HttpWorkerApi | None = None,
    worker_id: str = "w1",
    runtime: FakeRuntime | None = None,
    **settings: Any,
) -> Worker:
    defaults: dict[str, Any] = {"lease_s": 15, "poll_interval_s": 0.01, "blocked_pause_s": 60.0}
    return Worker(
        api=api or HttpWorkerApi(stack.client, TOKEN, retries=0),
        downloader=downloader,
        archiver=archiver if archiver is not None else Registering(stack),
        staging=stack.services.staging,
        library=stack.services.library,
        settings=WorkerSettings(**(defaults | settings)),
        worker_id=worker_id,
        runtime=runtime,
        clock=stack.clock,
        sleep=fast_sleep,
    )


def fake_downloader(stack: Stack, **knobs: Any) -> FakeDownloader:
    return FakeDownloader(stack.services.staging, chunks=4, sleep=no_sleep, **knobs)


# ---------------------------------------------------------------- the happy path


async def test_a_job_is_downloaded_archived_and_completed(stack: Stack) -> None:
    job_id = enqueue(stack)
    archiver = Registering(stack)
    worker = make_worker(stack, fake_downloader(stack), archiver=archiver)
    assert await worker.run_once() == 0.0
    job = stack.job(job_id)
    assert (job.state, job.attempts, job.progress, job.finished) == ("ready", 1, 1.0, True)
    assert job.format_id == "fake-opus"
    assert job.expected_size == job.bytes_downloaded
    assert job.final_path == f"{job_id}/1/{VIDEO}.opus"
    assert stack.track_status() == "ready"
    request = archiver.requests[0]
    assert request.download.final_path == f"{job_id}/1/{VIDEO}.opus"
    assert stack.services.library.exists(f"The Paper Lanterns/Lanterns at Dusk/{VIDEO}.opus")


async def test_an_empty_queue_waits_as_the_api_says(stack: Stack) -> None:
    worker = make_worker(stack, fake_downloader(stack))
    assert await worker.run_once() == 2.0


async def test_a_download_without_progress_still_reports_tagging(stack: Stack) -> None:
    job_id = enqueue(stack)
    assert await make_worker(stack, Silent(stack)).run_once() == 0.0
    job = stack.job(job_id)
    assert (job.state, job.bytes_downloaded, job.expected_size) == ("ready", 32, 32)


# ---------------------------------------------------------------- failures


async def test_a_retryable_failure_is_retried_after_the_backoff(stack: Stack) -> None:
    job_id = enqueue(stack)
    failing = fake_downloader(stack, fail_after_bytes=1)
    worker = make_worker(stack, failing)
    await worker.run_once()
    job = stack.job(job_id)
    assert (job.state, job.attempts, job.error_code) == ("queued", 1, "network_error")
    assert job.not_before is not None
    assert await worker.run_once() == 2.0
    stack.clock.advance(40)
    assert await make_worker(stack, fake_downloader(stack)).run_once() == 0.0
    job = stack.job(job_id)
    assert (job.state, job.attempts) == ("ready", 2)
    assert (job.previous_format_id, job.format_id) == ("fake-opus", "fake-opus")


async def test_without_an_archiver_the_job_fails_for_good(stack: Stack) -> None:
    job_id = enqueue(stack)
    worker = make_worker(stack, fake_downloader(stack), archiver=PendingArchiver())
    await worker.run_once()
    job = stack.job(job_id)
    assert (job.state, job.error_code) == ("failed", "tagging_failed")
    assert stack.track_status() == "failed"


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (DownloadError(WorkerErrorCode.VIDEO_UNAVAILABLE, "gone"), "video_unavailable"),
        (OSError(28, "No space left on device"), "storage_error"),
        (ApiUnavailableError("api down"), "internal_error"),
        (Conflict("odd"), "internal_error"),
        (RuntimeError("bug"), "internal_error"),
    ],
)
async def test_every_failure_releases_the_job(
    stack: Stack, error: BaseException, code: str
) -> None:
    job_id = enqueue(stack)
    await make_worker(stack, Raising(error)).run_once()
    assert stack.job(job_id).error_code == code


async def test_lost_reports_and_heartbeats_do_not_stop_the_work(stack: Stack) -> None:
    job_id = enqueue(stack)
    api = Flaky(stack.client, {"progress": 2, "heartbeat": 3})
    slow = FakeDownloader(stack.services.staging, chunks=4, delay_s=0.02)
    await make_worker(stack, slow, api=api).run_once()
    assert stack.job(job_id).state == "ready"
    assert api.failures == {"progress": 0, "heartbeat": 0}


async def test_an_undelivered_fail_leaves_the_job_to_its_lease(stack: Stack) -> None:
    job_id = enqueue(stack)
    api = Flaky(stack.client, {"fail": 1})
    await make_worker(stack, fake_downloader(stack, fail_after_bytes=1), api=api).run_once()
    assert stack.job(job_id).state == "downloading"
    stack.clock.advance(16)
    assert stack.services.jobs.expire_leases() == 1
    assert stack.job(job_id).error_code == "lease_expired"


async def test_an_unreachable_api_makes_the_worker_wait(stack: Stack) -> None:
    api = Flaky(stack.client, {"claim": 1})
    assert await make_worker(stack, fake_downloader(stack), api=api).run_once() == 0.01


# ---------------------------------------------------------------- leases, cancel, kill, stop


async def test_an_admin_cancel_stops_the_download(stack: Stack) -> None:
    job_id = enqueue(stack)
    stuck = Stuck(stack)
    worker = make_worker(stack, stuck)
    async with anyio.create_task_group() as tg:
        tg.start_soon(worker.run_once)
        await stuck.started.wait()
        stack.services.jobs.request_cancel(job_id)
    job = stack.job(job_id)
    assert (job.state, job.error_code) == ("cancelled", "cancelled")
    assert stack.track_status() == "failed"


async def test_a_cancel_seen_in_a_progress_answer(stack: Stack) -> None:
    job_id = enqueue(stack)

    class CancelledMeanwhile:
        async def download(
            self, video_id: str, job_dir: str, on_progress: ProgressCallback
        ) -> DownloadResult:
            stack.services.jobs.request_cancel(job_id)
            part = f"{job_dir}/{video_id}.opus.part"
            await on_progress(
                DownloadProgress(1, 9, part, part[:-5], False, "fake-opus", "audio/ogg", True)
            )
            raise AssertionError("the progress answer stops the download")

    async def never(_seconds: float) -> None:
        await anyio.sleep_forever()

    worker = make_worker(stack, CancelledMeanwhile())
    worker.sleep = never  # no heartbeat: the progress answer carries the cancel
    await worker.run_once()
    assert stack.job(job_id).state == "cancelled"


async def test_a_lost_lease_drops_the_work_without_failing(stack: Stack) -> None:
    job_id = enqueue(stack)
    stuck = Stuck(stack)
    worker = make_worker(stack, stuck)
    async with anyio.create_task_group() as tg:
        tg.start_soon(worker.run_once)
        await stuck.started.wait()
        stack.clock.advance(16)
        other = stack.services.jobs.claim("w2", lease_s=60)
        assert other is not None
    job = stack.job(job_id)
    assert (job.state, job.attempts, job.lease_owner) == ("downloading", 2, "w2")
    assert job.error_code == "lease_expired"


async def test_a_killed_worker_leaves_a_job_that_is_retried(stack: Stack) -> None:
    job_id = enqueue(stack)
    stuck = Stuck(stack)
    killed = make_worker(stack, stuck, worker_id="doomed")
    async with anyio.create_task_group() as tg:
        tg.start_soon(killed.run_once)
        await stuck.started.wait()
        tg.cancel_scope.cancel()  # SIGKILL: no fail, no cleanup
    job = stack.job(job_id)
    assert (job.state, job.lease_owner, job.bytes_downloaded) == ("downloading", "doomed", 10)
    # Nobody else gets it while the lease runs.
    survivor = make_worker(stack, fake_downloader(stack), worker_id="survivor")
    assert await survivor.run_once() == 2.0
    stack.clock.advance(16)
    assert await survivor.run_once() == 0.0
    job = stack.job(job_id)
    assert (job.state, job.attempts, job.error_code) == ("ready", 2, None)
    assert job.final_path == f"{job_id}/2/{VIDEO}.opus"
    assert stack.services.staging.exists(f"{job_id}/1/{VIDEO}.opus.part")
    assert stack.track_status() == "ready"


async def test_a_shutdown_releases_the_job_for_a_retry(stack: Stack) -> None:
    job_id = enqueue(stack)
    stuck = Stuck(stack)
    worker = make_worker(stack, stuck)
    stop = anyio.Event()
    async with anyio.create_task_group() as tg:
        tg.start_soon(worker.run_once, stop)
        await stuck.started.wait()
        stop.set()
    job = stack.job(job_id)
    assert (job.state, job.error_code, job.error_message) == (
        "queued",
        "internal_error",
        "worker shutting down",
    )


# ---------------------------------------------------------------- breaker, updates, status


async def test_a_bot_wall_pauses_claiming_and_doubles(stack: Stack) -> None:
    job_id = enqueue(stack)
    blocked = Raising(DownloadError(WorkerErrorCode.RATE_LIMITED_UPSTREAM, "429"))
    worker = make_worker(stack, blocked, blocked_pause_max_s=100.0)
    await worker.run_once()
    assert stack.job(job_id).state == "queued"
    assert worker.paused_until == stack.clock.monotonic() + 60
    assert await worker.run_once() == 0.01
    stack.clock.advance(61)
    await worker.run_once()
    assert worker.paused_until == stack.clock.monotonic() + 100
    stack.clock.advance(101)
    worker.downloader = fake_downloader(stack)
    enqueue(stack, "t2", "Wq5Jd7HsKe2")
    await worker.run_once()
    assert worker.pause_s == 60


async def test_extractor_errors_trigger_an_update_at_most_hourly(stack: Stack) -> None:
    job_id = enqueue(stack)
    runtime = FakeRuntime()
    broken = Raising(DownloadError(WorkerErrorCode.EXTRACTOR_ERROR, "n challenge"))
    worker = make_worker(stack, broken, runtime=runtime)
    await worker.run_once()
    assert runtime.updates == 1
    stack.clock.advance(40)  # past the first backoff, whatever its jitter
    await worker.run_once()
    assert runtime.updates == 1
    stack.clock.advance(3600)
    await worker.run_once()
    assert runtime.updates == 2
    assert stack.job(job_id).state == "failed"


async def test_status_reports_carry_versions_and_bring_commands(stack: Stack) -> None:
    with stack.db.transaction() as conn:
        for command_id, command in (("c1", "update_ytdlp"), ("c2", "run_canary")):
            conn.execute(
                "INSERT INTO worker_commands (id, command, created_at) VALUES (?, ?, ?)",
                (command_id, command, "2026-10-12T07:00:00.000Z"),
            )
    runtime = FakeRuntime()
    worker = make_worker(stack, fake_downloader(stack), runtime=runtime)
    await worker.housekeeping()
    # One update for the admin command, one because the periodic check is due at start.
    assert runtime.updates == 2
    with stack.db.read() as conn:
        row = conn.execute("SELECT ytdlp_version FROM worker_status WHERE worker_id = 'w1'")
        assert row.scalar() == "2026.08.19"
    await worker.housekeeping()
    assert runtime.updates == 2
    runtime.version = None
    assert worker.ytdlp_version() == "unknown"
    assert make_worker(stack, fake_downloader(stack)).ytdlp_version() == "fake"


async def test_housekeeping_survives_failures(stack: Stack) -> None:
    api = Flaky(stack.client, {"report_status": 1})
    runtime = FakeRuntime(fail_update=True)
    worker = make_worker(stack, fake_downloader(stack), api=api, runtime=runtime)
    await worker.housekeeping()
    assert runtime.updates == 1
    await make_worker(stack, fake_downloader(stack)).update_ytdlp()


async def test_the_loop_runs_until_stopped(stack: Stack) -> None:
    runtime = FakeRuntime(fail_install=True)
    worker = make_worker(stack, fake_downloader(stack), runtime=runtime)
    stop = anyio.Event()
    async with anyio.create_task_group() as tg:
        tg.start_soon(worker.run, stop)
        await anyio.sleep(0.05)
        stop.set()
    assert runtime.installs == 1
    runtime.fail_install = False
    await worker.start()
    assert runtime.installs == 2


# ---------------------------------------------------------------- the process


class IdleApi:
    """Answers 'no job' forever (for the process-level tests)."""

    async def claim(self, worker_id: str, lease_s: int) -> NoJob:
        return NoJob(0.05)

    async def report_status(self, worker_id: str, **fields: Any) -> list[str]:
        return []


def test_worker_stops_on_sigterm(settings: Settings) -> None:
    handlers: dict[int, Handler] = {}

    def install(signum: int, handler: Handler) -> None:
        handlers[signum] = handler

    def factory(s: Settings, w: WorkerSettings, client: httpx.AsyncClient) -> Worker:
        return Worker(
            api=IdleApi(),  # type: ignore[arg-type]
            downloader=FakeDownloader(LocalStagingStore(s.staging_dir)),
            archiver=PendingArchiver(),
            staging=LocalStagingStore(s.staging_dir),
            library=LocalLibraryStore(s.music_dir),
            settings=w,
            worker_id="w-test",
        )

    stop = threading.Event()
    thread = threading.Thread(
        target=run_worker, args=(settings, WorkerSettings(), stop, install, factory)
    )
    thread.start()
    while signal.SIGTERM not in handlers:
        thread.join(timeout=0.01)
    handlers[signal.SIGTERM](signal.SIGTERM, None)
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert signal.SIGINT in handlers


async def test_build_worker_picks_the_downloader(settings: Settings) -> None:
    async with httpx.AsyncClient() as client:
        fake = build_worker(
            settings.model_copy(update={"fake_youtube": True, "worker_token": SecretStr(TOKEN)}),
            WorkerSettings(worker_id="w9"),
            client,
        )
        assert isinstance(fake.downloader, FakeDownloader)
        assert (fake.runtime, fake.worker_id) == (None, "w9")
        real = build_worker(
            settings.model_copy(update={"fake_youtube": False}), WorkerSettings(), client
        )
        assert isinstance(real.downloader, YtDlpDownloader)
        assert real.runtime is not None
        assert real.worker_id == loop.default_worker_id()


def test_worker_command_runs_the_loop(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Settings] = []

    def run_stub(s: Settings) -> int:
        seen.append(s)
        return 0

    monkeypatch.setattr(loop, "run_worker", run_stub)
    registry = CommandRegistry()
    worker_cli.register(registry)
    assert registry.get("worker").run(settings, []) == 0
    assert seen == [settings]


def test_worker_settings_come_from_ut_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    assert WorkerSettings().api_url == "http://api:8044"
    monkeypatch.setenv("UT_API_URL", "http://api.internal:8044")
    monkeypatch.setenv("UT_WORKER_ID", "worker-1")
    monkeypatch.setenv("UT_YTDLP_PLAYER_CLIENTS", "default,web_embedded")
    configured = WorkerSettings()
    assert (configured.api_url, configured.worker_id) == ("http://api.internal:8044", "worker-1")
    assert configured.ytdlp_player_clients == "default,web_embedded"
    monkeypatch.setenv("UT_YTDLP_PLAYER_CLIENTS", "default; rm -rf")
    with pytest.raises(ValueError, match="pattern"):
        WorkerSettings()
