# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Worker side of the canary: the T08 worker loop plus the download check.

`CanaryWorker` is the T08 `Worker` with two additions, both between jobs (`housekeeping`):
- the download canary runs once `UT_CANARY_INTERVAL_H` has passed since the last run (kept
  in `UT_CANARY_STATE_FILE`, since the worker has no database), the first time
  `UT_CANARY_FIRST_DELAY_S` after start, and at once when the admin's `run_canary` command
  arrives with a status report;
- every status report carries the last canary result (`canary` in the contract), which the
  api stores once in `canary_runs` (source `worker`); a run asks for a report right away.

`build_canary_worker` is a `WorkerFactory` for `run_worker`: it builds the T08 worker and
wraps it, so the downloader (yt-dlp, or the fake with `UT_FAKE_YOUTUBE`) is the very one jobs
use.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from ultimatetunes import __version__
from ultimatetunes.canary.checks import DownloadCanary, Report, targets
from ultimatetunes.canary.settings import CanarySettings
from ultimatetunes.core.clock import format_ts, parse_ts
from ultimatetunes.errors import TunesError
from ultimatetunes.settings import Settings
from ultimatetunes.worker.client import ApiUnavailableError
from ultimatetunes.worker.loop import Worker, build_worker
from ultimatetunes.worker.settings import WorkerSettings

log = logging.getLogger(__name__)


class CanaryState:
    """When the worker's canary last ran, in a small JSON file (memory if it cannot be
    written: a read-only or missing volume only costs an extra run after a restart)."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._last: datetime | None = None
        self._loaded = False

    def last_run(self) -> datetime | None:
        if not self._loaded:
            self._loaded = True
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._last = parse_ts(str(data["lastRun"]))
            except (OSError, ValueError, KeyError, TypeError):
                self._last = None
        return self._last

    def save(self, moment: datetime) -> None:
        self._last = moment
        self._loaded = True
        try:
            tmp = self._path.with_name(f".{self._path.name}.tmp")
            tmp.write_text(json.dumps({"lastRun": format_ts(moment)}), encoding="utf-8")
            tmp.replace(self._path)
        except OSError as exc:
            log.warning("canary: cannot remember the last run in %s: %s", self._path, exc)


class CanaryWorker(Worker):
    def __init__(
        self, *, canary: CanarySettings, state: CanaryState, video_id: str, **worker: Any
    ) -> None:
        super().__init__(**worker)
        self.canary = canary
        self.state = state
        self.video_id = video_id
        self.last_report: Report | None = None
        self._first_at = self.clock.monotonic() + canary.canary_first_delay_s

    @classmethod
    def wrap(
        cls, worker: Worker, canary: CanarySettings, state: CanaryState, video_id: str
    ) -> "CanaryWorker":
        return cls(
            canary=canary,
            state=state,
            video_id=video_id,
            api=worker.api,
            downloader=worker.downloader,
            archiver=worker.archiver,
            staging=worker.staging,
            library=worker.library,
            settings=worker.settings,
            worker_id=worker.worker_id,
            runtime=worker.runtime,
            clock=worker.clock,
            sleep=worker.sleep,
        )

    def canary_due(self) -> bool:
        if not self.canary.canary_enabled or self.clock.monotonic() < self._first_at:
            return False
        last = self.state.last_run()
        interval = timedelta(hours=self.canary.canary_interval_h)
        return last is None or self.clock.now() - last >= interval

    async def housekeeping(self) -> None:
        if self.canary_due():
            await self.run_canary()
        await super().housekeeping()

    async def run_canary(self) -> Report:
        check = DownloadCanary(
            self.downloader, self.staging, self.video_id, self.clock, self.canary.canary_timeout_s
        )
        report = await check.run()
        self.state.save(self.clock.now())
        self.last_report = report
        if report.ok:
            log.info("worker %s: canary ok", self.worker_id)
        else:
            log.warning("worker %s: canary failed: %s", self.worker_id, report.message)
        # Tell the api now, not at the next scheduled report.
        self._next_status = 0.0
        return report

    async def report_status(self) -> None:
        canary = self.last_report.as_status() if self.last_report else None
        try:
            commands = await self.api.report_status(
                self.worker_id,
                version=__version__,
                ytdlp_version=self.ytdlp_version(),
                canary=canary,
            )
        except (ApiUnavailableError, TunesError) as exc:
            log.warning("worker %s: status report failed: %s", self.worker_id, exc)
            return
        for command in commands:
            if command == "update_ytdlp":
                await self.update_ytdlp()
            elif command == "run_canary":
                await self.run_canary()
            else:
                log.warning("worker %s: unknown command %s ignored", self.worker_id, command)


def build_canary_worker(
    settings: Settings, worker: WorkerSettings, client: httpx.AsyncClient
) -> CanaryWorker:
    """`run_worker(settings, factory=build_canary_worker)`: the production worker with the
    download canary."""
    canary = CanarySettings()
    target = targets(
        settings, canary.canary_video_id, canary.canary_query, canary.canary_playlist_id
    )
    state = CanaryState(canary.canary_state_file)
    return CanaryWorker.wrap(build_worker(settings, worker, client), canary, state, target.video_id)
