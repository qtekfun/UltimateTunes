# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The worker main loop (PLAN T08). No database access: everything goes through `WorkerApi`.

    claim (lease) ─▶ download into <job>/<attempt> ─▶ progress (≤ 0.5 s while it grows)
                 ─▶ progress `tagging` ─▶ archiver (T09: tag, register, move) ─▶ complete

- A heartbeat runs next to the work every `heartbeatSeconds`. `lease_lost` (or a vanished
  job) stops the work at once and discards it, without calling `fail`: the job already
  belongs to someone else. `cancelRequested` (heartbeat or progress) stops the work and ends
  the job with `fail` `cancelled`.
- Failures end with `fail` and the worker's error code; the api decides the retry and its
  backoff (contracts/errors.md). An `extractor_error` also triggers a yt-dlp update (at most
  once per `ytdlp_update_on_error_min_interval_s`); `rate_limited_upstream` pauses claiming
  (circuit breaker, doubling up to a maximum) instead of burning every job's attempts.
- SIGTERM/SIGINT stop claiming; a job still downloading is stopped and released with a
  retryable `fail`, so another worker can take it after the backoff (that release counts as an
  attempt: the contract has no "release without consuming"). Once archiving has started
  (register, move, complete), neither a shutdown nor an admin cancel interrupts it. A worker
  that is killed outright releases nothing: its lease runs out and the next claim re-queues it.
- On start, and every `status_interval_s`, the worker reports its versions; the answer carries
  admin commands (`update_ytdlp`; `run_canary` belongs to PLAN T19).
"""

import logging
import os
import signal
import socket
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from types import FrameType
from typing import Protocol

import anyio
import httpx

from ultimatetunes import __version__
from ultimatetunes.core.clock import Clock, SystemClock
from ultimatetunes.core.storage import (
    LibraryStore,
    LocalLibraryStore,
    LocalStagingStore,
    StagingStore,
)
from ultimatetunes.errors import LeaseLost, NotFound, TunesError, WorkerErrorCode
from ultimatetunes.settings import Settings
from ultimatetunes.worker.archiver import Archiver, ArchiveRequest, default_archiver
from ultimatetunes.worker.client import (
    ApiUnavailableError,
    ClaimedJob,
    HttpWorkerApi,
    NoJob,
    WorkerApi,
)
from ultimatetunes.worker.downloader import (
    Downloader,
    DownloadError,
    DownloadProgress,
    DownloadResult,
)
from ultimatetunes.worker.settings import WorkerSettings
from ultimatetunes.worker.ytdlp_runtime import UpdateError, UpdateResult

log = logging.getLogger(__name__)

SignalInstaller = Callable[[int, Callable[[int, FrameType | None], None]], object]
Sleep = Callable[[float], Awaitable[None]]
# How often the loop looks at the persisted time of the last yt-dlp update check.
UPDATE_CHECK_EVERY_S = 60.0


class Runtime(Protocol):
    """The yt-dlp install (`YtDlpRuntime`): version, seed install and update."""

    def current_version(self) -> str | None: ...

    async def ensure_installed(self) -> str: ...

    def update_due(self, interval_s: float) -> bool: ...

    async def update(self, *, force: bool = False) -> UpdateResult: ...


@dataclass
class JobRun:
    """What happened to one claimed job."""

    job: ClaimedJob
    done: bool = False
    lost: bool = False
    cancel_requested: bool = False
    shutdown: bool = False
    archiving: bool = False
    error: DownloadError | None = None
    last: DownloadProgress | None = None


def default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"[:100]


class Worker:
    def __init__(  # noqa: PLR0913 - the collaborators of the loop, all injected
        self,
        *,
        api: WorkerApi,
        downloader: Downloader,
        archiver: Archiver,
        staging: StagingStore,
        library: LibraryStore,
        settings: WorkerSettings,
        worker_id: str,
        runtime: Runtime | None = None,
        clock: Clock | None = None,
        sleep: Sleep = anyio.sleep,
    ) -> None:
        self.api = api
        self.downloader = downloader
        self.archiver = archiver
        self.staging = staging
        self.library = library
        self.settings = settings
        self.worker_id = worker_id
        self.runtime = runtime
        self.clock = clock or SystemClock()
        self.sleep = sleep
        self.paused_until = 0.0
        self.pause_s = settings.blocked_pause_s
        self._next_status = 0.0
        self._next_update = 0.0
        self._last_error_update: float | None = None

    # ------------------------------------------------------------ main loop

    async def run(self, stop: anyio.Event) -> None:
        """Claims and processes jobs until `stop` is set."""
        await self.start()
        while not stop.is_set():
            await self.housekeeping()
            wait = await self.run_once(stop)
            if wait > 0:
                with anyio.move_on_after(wait):
                    await stop.wait()
        log.info("worker %s stopped", self.worker_id)

    async def start(self) -> None:
        if self.runtime is not None:
            try:
                version = await self.runtime.ensure_installed()
                log.info("worker %s: yt-dlp %s", self.worker_id, version)
            except (UpdateError, OSError) as exc:
                log.warning("worker %s: yt-dlp is not installed: %s", self.worker_id, exc)

    async def run_once(self, stop: anyio.Event | None = None) -> float:
        """One claim and, if there is a job, its processing. Returns how long to wait before
        the next claim (0 right after a job)."""
        now = self.clock.monotonic()
        if self.paused_until > now:
            return min(self.paused_until - now, self.settings.poll_interval_s)
        try:
            claimed = await self._claim(stop)
        except (ApiUnavailableError, TunesError) as exc:
            log.warning("worker %s: claim failed: %s", self.worker_id, exc)
            return self.settings.poll_interval_s
        if claimed is None:  # stopping
            return 0.0
        if isinstance(claimed, NoJob):
            if claimed.retry_after_s is None:
                return self.settings.poll_interval_s
            return claimed.retry_after_s
        await self.process(claimed, stop or anyio.Event())
        return 0.0

    async def _claim(self, stop: anyio.Event | None) -> ClaimedJob | NoJob | None:
        """The claim, abandoned (None) when `stop` is set while the api holds it (long poll):
        a stopping worker does not wait for it, and the api hands nothing to a closed one."""
        if stop is None:
            return await self.api.claim(self.worker_id, self.settings.lease_s)
        claimed: ClaimedJob | NoJob | None = None
        error: ApiUnavailableError | TunesError | None = None
        async with anyio.create_task_group() as tg:

            async def cancel_on_stop() -> None:
                await stop.wait()
                tg.cancel_scope.cancel()

            tg.start_soon(cancel_on_stop)
            try:
                claimed = await self.api.claim(self.worker_id, self.settings.lease_s)
            except (ApiUnavailableError, TunesError) as exc:  # raised below, not as a group
                error = exc
            tg.cancel_scope.cancel()
        if error is not None:
            raise error
        return claimed

    # ------------------------------------------------------------ one job

    async def process(self, job: ClaimedJob, stop: anyio.Event) -> JobRun:
        log.info(
            "worker %s: job %s attempt %d/%d",
            self.worker_id,
            job.job_id,
            job.attempt,
            job.max_attempts,
        )
        run = JobRun(job)
        async with anyio.create_task_group() as tg:
            tg.start_soon(self._keep_alive, run, tg.cancel_scope)
            tg.start_soon(self._watch_stop, run, stop, tg.cancel_scope)
            await self._guarded(run)
            tg.cancel_scope.cancel()
        await self._settle(run)
        return run

    async def _guarded(self, run: JobRun) -> None:
        try:
            await self._work(run)
            run.done = True
        except (LeaseLost, NotFound):
            run.lost = True
        except DownloadError as error:
            run.error = error
        except ApiUnavailableError as exc:
            run.error = DownloadError(WorkerErrorCode.INTERNAL_ERROR, f"api unavailable: {exc}")
        except TunesError as exc:
            run.error = DownloadError(WorkerErrorCode.INTERNAL_ERROR, exc.message)
        except OSError as exc:
            run.error = DownloadError(WorkerErrorCode.STORAGE_ERROR, exc.strerror or "I/O error")
        except Exception as exc:
            log.exception("worker %s: job %s crashed", self.worker_id, run.job.job_id)
            run.error = DownloadError(WorkerErrorCode.INTERNAL_ERROR, type(exc).__name__)

    async def _work(self, run: JobRun) -> None:
        job = run.job

        async def on_progress(report: DownloadProgress) -> None:
            run.last = report
            await self._report(run, "downloading", report)

        download = await self.downloader.download(
            job.video_id, job.staging_dir, on_progress, cookies=job.youtube_cookies
        )
        await self._report(run, "tagging", self._final_report(run, download))
        # From register on, stopping halfway would leave a reserved path or a moved file
        # without `complete`: a shutdown or an admin cancel no longer interrupts, it waits.
        with anyio.CancelScope(shield=True):
            run.archiving = True
            archived = await self.archiver.archive(
                ArchiveRequest(job, download, self.api, self.staging, self.library)
            )
            await self.api.complete(
                job,
                track_id=archived.track_id,
                library_path=archived.library_path,
                staging_path=download.final_path,
                staging_size=download.size_bytes,
            )
        log.info("worker %s: job %s complete", self.worker_id, job.job_id)

    @staticmethod
    def _final_report(run: JobRun, download: DownloadResult) -> DownloadProgress:
        if run.last is not None:
            return replace(run.last, downloaded_bytes=download.size_bytes, finished=True)
        return DownloadProgress(
            downloaded_bytes=download.size_bytes,
            expected_size=download.size_bytes,
            part_path=f"{download.final_path}.part",
            final_path=download.final_path,
            finished=True,
            format_id=download.format_id,
            content_type=download.content_type,
            progressive=False,
        )

    async def _report(self, run: JobRun, state: str, report: DownloadProgress) -> None:
        """A progress report. Losing one to a transport error is fine (the next one follows);
        a lost lease or an admin cancel stops the work."""
        try:
            info = await self.api.progress(run.job, state, report)
        except ApiUnavailableError as exc:
            log.warning("worker %s: progress not delivered: %s", self.worker_id, exc)
            return
        if info.cancel_requested:
            run.cancel_requested = True
            raise DownloadError(WorkerErrorCode.CANCELLED, "cancelled by an admin")

    async def _keep_alive(self, run: JobRun, scope: anyio.CancelScope) -> None:
        while True:
            await self.sleep(run.job.heartbeat_s)
            try:
                info = await self.api.heartbeat(run.job, self.settings.lease_s)
            except (LeaseLost, NotFound):
                run.lost = True
                scope.cancel()
                return
            except (ApiUnavailableError, TunesError) as exc:
                log.warning("worker %s: heartbeat failed: %s", self.worker_id, exc)
                continue
            if info.cancel_requested:
                run.cancel_requested = True
                if not run.archiving:
                    scope.cancel()
                    return
                # Archiving: keep the lease alive until register, move and complete are done.

    @staticmethod
    async def _watch_stop(run: JobRun, stop: anyio.Event, scope: anyio.CancelScope) -> None:
        await stop.wait()
        run.shutdown = True
        if not run.archiving:
            scope.cancel()

    async def _settle(self, run: JobRun) -> None:
        job = run.job
        if run.done:
            self.pause_s = self.settings.blocked_pause_s
            return
        if run.lost:
            log.warning("worker %s: lease of job %s lost, work dropped", self.worker_id, job.job_id)
            return
        if run.cancel_requested:
            error = DownloadError(WorkerErrorCode.CANCELLED, "cancelled by an admin")
        elif run.error is not None:
            error = run.error
        else:
            error = DownloadError(WorkerErrorCode.INTERNAL_ERROR, "worker shutting down")
        log.info("worker %s: job %s failed: %s", self.worker_id, job.job_id, error)
        try:
            await self.api.fail(
                job, error_code=error.code.value, retryable=error.retryable, message=error.message
            )
        except (ApiUnavailableError, TunesError) as exc:
            # The lease runs out and the api re-queues the job.
            log.warning("worker %s: fail not delivered: %s", self.worker_id, exc)
        await self._react(error.code)

    async def _react(self, code: WorkerErrorCode) -> None:
        now = self.clock.monotonic()
        if code == WorkerErrorCode.RATE_LIMITED_UPSTREAM:
            self.paused_until = now + self.pause_s
            log.warning(
                "worker %s: YouTube blocks us, pausing %.0f s", self.worker_id, self.pause_s
            )
            self.pause_s = min(self.pause_s * 2, self.settings.blocked_pause_max_s)
        elif code == WorkerErrorCode.EXTRACTOR_ERROR:
            last = self._last_error_update
            if last is None or now - last >= self.settings.ytdlp_update_on_error_min_interval_s:
                self._last_error_update = now
                await self.update_ytdlp()

    # ------------------------------------------------------------ housekeeping

    async def housekeeping(self) -> None:
        now = self.clock.monotonic()
        if now >= self._next_status:
            self._next_status = now + self.settings.status_interval_s
            await self.report_status()
        runtime = self.runtime
        if runtime is not None and self.settings.ytdlp_auto_update and now >= self._next_update:
            # The last check is persisted in the volume, so restarts do not hit GitHub again.
            self._next_update = now + UPDATE_CHECK_EVERY_S
            if runtime.update_due(self.settings.ytdlp_update_interval_h * 3600):
                await self.update_ytdlp()

    def ytdlp_version(self) -> str:
        if self.runtime is None:
            return "fake"
        return self.runtime.current_version() or "unknown"

    async def report_status(self) -> None:
        try:
            commands = await self.api.report_status(
                self.worker_id, version=__version__, ytdlp_version=self.ytdlp_version()
            )
        except (ApiUnavailableError, TunesError) as exc:
            log.warning("worker %s: status report failed: %s", self.worker_id, exc)
            return
        for command in commands:
            if command == "update_ytdlp":
                await self.update_ytdlp()
            else:
                log.info("worker %s: command %s is not available yet", self.worker_id, command)

    async def update_ytdlp(self) -> None:
        if self.runtime is None:
            return
        try:
            result = await self.runtime.update()
        except (UpdateError, OSError) as exc:
            log.warning("worker %s: yt-dlp update failed: %s", self.worker_id, exc)
            return
        if result.updated:
            log.info("worker %s: yt-dlp is now %s", self.worker_id, result.version)


WorkerFactory = Callable[[Settings, WorkerSettings, httpx.AsyncClient], Worker]


def build_worker(settings: Settings, worker: WorkerSettings, client: httpx.AsyncClient) -> Worker:
    """The production worker: yt-dlp (or the fake with `UT_FAKE_YOUTUBE`), the api over
    `client`, and the archiver (T09)."""
    staging = LocalStagingStore(settings.staging_dir)
    library = LocalLibraryStore(settings.music_dir)
    token = settings.worker_token.get_secret_value() if settings.worker_token else ""
    if not token:
        log.error("UT_WORKER_TOKEN is not set: the api will refuse every call")
    api = HttpWorkerApi(client, token, retries=worker.api_retries, claim_wait_s=worker.claim_wait_s)
    runtime: Runtime | None = None
    downloader: Downloader
    if settings.fake_youtube:
        from ultimatetunes.worker.fake import FakeDownloader  # noqa: PLC0415

        downloader = FakeDownloader(
            staging, chunks=worker.fake_download_chunks, delay_s=worker.fake_download_delay_s
        )
    else:
        from ultimatetunes.worker.ytdlp import YtDlpDownloader  # noqa: PLC0415
        from ultimatetunes.worker.ytdlp_runtime import YtDlpRuntime  # noqa: PLC0415

        ytdlp = YtDlpRuntime(worker)
        runtime = ytdlp
        downloader = YtDlpDownloader(staging, worker, ytdlp)
        if worker.ytdlp_pot_provider_url is not None:
            # A bare base URL (validated: no credentials, path or query), safe to log.
            log.info("yt-dlp: PO token provider at %s", worker.ytdlp_pot_provider_url)
    return Worker(
        api=api,
        downloader=downloader,
        archiver=default_archiver(settings),
        staging=staging,
        library=library,
        settings=worker,
        worker_id=worker.worker_id or default_worker_id(),
        runtime=runtime,
    )


def run_worker(
    settings: Settings,
    worker_settings: WorkerSettings | None = None,
    stop: threading.Event | None = None,
    install: SignalInstaller = signal.signal,
    factory: WorkerFactory = build_worker,
) -> int:
    worker_settings = worker_settings or WorkerSettings()
    stop = stop or threading.Event()
    # httpx logs every request at INFO: one line per idle claim is noise (issue #55).
    logging.getLogger("httpx").setLevel(logging.WARNING)

    def _on_signal(signum: int, _frame: FrameType | None) -> None:
        log.info("worker: signal %s received, stopping", signum)
        stop.set()

    install(signal.SIGTERM, _on_signal)
    install(signal.SIGINT, _on_signal)

    async def main() -> None:
        async with httpx.AsyncClient(
            base_url=worker_settings.api_url, timeout=worker_settings.api_timeout_s
        ) as client:
            worker = factory(settings, worker_settings, client)
            log.info(
                "worker %s started (staging=%s, api=%s)",
                worker.worker_id,
                settings.staging_dir,
                worker_settings.api_url,
            )
            stopped = anyio.Event()
            async with anyio.create_task_group() as tg:
                tg.start_soon(_bridge, stop, stopped)
                await worker.run(stopped)
                tg.cancel_scope.cancel()

    anyio.run(main)
    log.info("worker stopped")
    return 0


async def _bridge(stop: threading.Event, stopped: anyio.Event) -> None:
    """Signals arrive on a `threading.Event`; the async loop waits on an `anyio.Event`."""
    await anyio.to_thread.run_sync(stop.wait, abandon_on_cancel=True)
    stopped.set()
