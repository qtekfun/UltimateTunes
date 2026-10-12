# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Commands of the canary area (`commands.AREAS`). Owner: PLAN T19.

`ultimatetunes canary [--only catalog|download]` runs the canary once, by hand, without the
api or a database: the catalog checks (ytmusicapi, uncached) and the download check (yt-dlp
from `/opt/ytdlp`, installed from the image's seed if needed, into `/staging`, deleted
afterwards). It prints one JSON report per side and exits 0 when everything passed, 1
otherwise. The manual GitHub job (`nightly.yml`) runs exactly this in the image. The scheduled
canary is not this command: it runs inside the api (`canary/web.py`) and the worker
(`canary/worker.py`) and is recorded in `canary_runs`. With `UT_FAKE_YOUTUBE` both sides use
the fakes (test stack).
"""

import argparse
import json
import sys
from collections.abc import Awaitable, Callable, Sequence

import anyio

from ultimatetunes.canary.checks import CatalogCanary, DownloadCanary, Report, targets
from ultimatetunes.canary.settings import CanarySettings
from ultimatetunes.commands import CommandRegistry
from ultimatetunes.core.clock import Clock, SystemClock
from ultimatetunes.core.storage import LocalStagingStore
from ultimatetunes.search.catalog import MusicCatalog
from ultimatetunes.settings import Settings
from ultimatetunes.worker.downloader import Downloader

SIDES = ("catalog", "download")


def build_catalog(settings: Settings) -> MusicCatalog:
    if settings.fake_youtube:
        from ultimatetunes.search.fake import FakeMusicCatalog  # noqa: PLC0415

        return FakeMusicCatalog()
    from ultimatetunes.search.settings import SearchSettings  # noqa: PLC0415
    from ultimatetunes.search.ytmusic import YTMusicCatalog  # noqa: PLC0415

    return YTMusicCatalog.build(SearchSettings())


async def build_downloader(settings: Settings) -> Downloader:
    staging = LocalStagingStore(settings.staging_dir)
    if settings.fake_youtube:
        from ultimatetunes.worker.fake import FakeDownloader  # noqa: PLC0415

        return FakeDownloader(staging, delay_s=0)
    from ultimatetunes.worker.settings import WorkerSettings  # noqa: PLC0415
    from ultimatetunes.worker.ytdlp import YtDlpDownloader  # noqa: PLC0415
    from ultimatetunes.worker.ytdlp_runtime import YtDlpRuntime  # noqa: PLC0415

    worker = WorkerSettings()
    runtime = YtDlpRuntime(worker)
    await runtime.ensure_installed()
    return YtDlpDownloader(staging, worker, runtime)


CatalogBuilder = Callable[[Settings], MusicCatalog]
DownloaderBuilder = Callable[[Settings], Awaitable[Downloader]]


async def run_canary(  # noqa: PLR0913 - the collaborators of one run, all injectable
    settings: Settings,
    canary: CanarySettings,
    sides: Sequence[str] = SIDES,
    *,
    clock: Clock | None = None,
    catalog: CatalogBuilder | None = None,
    downloader: DownloaderBuilder | None = None,
) -> list[Report]:
    clock = clock or SystemClock()
    catalog = catalog or build_catalog
    downloader = downloader or build_downloader
    target = targets(
        settings, canary.canary_video_id, canary.canary_query, canary.canary_playlist_id
    )
    reports = []
    if "catalog" in sides:
        checks = CatalogCanary(catalog(settings), target, clock, canary.canary_timeout_s)
        reports.append(await checks.run())
    if "download" in sides:
        staging = LocalStagingStore(settings.staging_dir)
        download = DownloadCanary(
            await downloader(settings), staging, target.video_id, clock, canary.canary_timeout_s
        )
        reports.append(await download.run())
    return reports


def report_line(report: Report) -> str:
    return json.dumps(
        {
            "side": "catalog" if report.source == "api" else "download",
            "ranAt": report.ran_at,
            "ok": report.ok,
            "message": report.message,
            "checks": json.loads(report.detail_json()),
        }
    )


def run_command(settings: Settings, args: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="ultimatetunes canary", description=__doc__)
    parser.add_argument("--only", choices=SIDES, help="run one side only")
    parsed = parser.parse_args(list(args))
    sides = (parsed.only,) if parsed.only else SIDES
    reports = anyio.run(run_canary, settings, CanarySettings(), sides)
    for report in reports:
        sys.stdout.write(report_line(report) + "\n")
    return 0 if all(r.ok for r in reports) else 1


def register(registry: CommandRegistry) -> None:
    registry.add("canary", run_command, help="Run the canary once (YouTube Music + yt-dlp)")
