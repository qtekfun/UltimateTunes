# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The production worker loop with a throttled fake download, for first-sound timing (PLAN T21).

Real downloads are not allowed in tests and measurements (CLAUDE.md), so the external
first-sound run replaces only the downloader: the same claim, progress reports, streaming while
downloading, archive and tagging as `ultimatetunes worker`, but the bytes come from a generated
audio file (`UT_BENCH_AUDIO`: an ffmpeg tone, see docs/measurements.md; no real music) at a
modelled YouTube pace:

- `UT_BENCH_FIRST_BYTE_S` (default 1.8): yt-dlp extraction plus googlevideo time to headers on
  the default client path, measured in spike T03c (1.5-1.8 s + 30-80 ms). 3.9 models the
  `web_embedded` + Deno fallback (3.7-3.8 s).
- `UT_BENCH_RATE_KBPS` (default 8000 kbit/s, i.e. 1 MB/s): a throttled googlevideo rate, far
  below the home link but well above the ~130 kbit/s the audio needs.

Progress is reported every `UT_BENCH_REPORT_S` (0.25 s), with the exact size from the first
report, like the real downloader. Run inside the worker container (compose.firstsound.yaml):
    python /bench/throttled_worker.py
"""

import os
import sys
from pathlib import Path

import anyio
import httpx

from ultimatetunes.core.storage import StagingStore
from ultimatetunes.logging import configure_logging
from ultimatetunes.settings import Settings
from ultimatetunes.worker.downloader import (
    DownloadProgress,
    DownloadResult,
    ProgressCallback,
    check_video_id,
)
from ultimatetunes.worker.loop import Worker, build_worker, run_worker
from ultimatetunes.worker.settings import WorkerSettings

CONTENT_TYPE = "audio/ogg"
FORMAT_ID = "bench-throttled-opus"


class ThrottledDownloader:
    def __init__(  # noqa: PLR0913 - the knobs of the model
        self,
        *,
        staging: StagingStore,
        audio: bytes,
        duration_ms: int,
        first_byte_s: float,
        rate_bytes_s: float,
        report_s: float,
    ) -> None:
        self._staging = staging
        self._audio = audio
        self._duration_ms = duration_ms
        self._first_byte_s = first_byte_s
        self._rate = rate_bytes_s
        self._report_s = report_s

    async def download(
        self, video_id: str, job_dir: str, on_progress: ProgressCallback
    ) -> DownloadResult:
        check_video_id(video_id)
        final = f"{job_dir}/{video_id}.opus"
        part = f"{final}.part"
        total = len(self._audio)
        step = max(1, int(self._rate * self._report_s))
        written = 0

        def report(*, finished: bool) -> DownloadProgress:
            return DownloadProgress(
                downloaded_bytes=written,
                expected_size=total,
                part_path=part,
                final_path=final,
                finished=finished,
                format_id=FORMAT_ID,
                content_type=CONTENT_TYPE,
                progressive=True,
            )

        await anyio.sleep(self._first_byte_s)
        with self._staging.open_write(part) as out:
            while written < total:
                chunk = self._audio[written : written + step]
                out.write(chunk)
                out.flush()
                written += len(chunk)
                await on_progress(report(finished=False))
                await anyio.sleep(len(chunk) / self._rate)
        self._staging.rename(part, final)
        await on_progress(report(finished=True))
        return DownloadResult(final, FORMAT_ID, "opus", CONTENT_TYPE, total, self._duration_ms)


def main() -> int:
    settings = Settings()
    configure_logging(settings.log_level)
    audio = Path(os.environ.get("UT_BENCH_AUDIO", "/bench-audio/tone.opus")).read_bytes()
    duration_ms = int(os.environ.get("UT_BENCH_DURATION_MS", "240000"))
    first_byte_s = float(os.environ.get("UT_BENCH_FIRST_BYTE_S", "1.8"))
    rate = float(os.environ.get("UT_BENCH_RATE_KBPS", "8000")) * 1000 / 8
    report_s = float(os.environ.get("UT_BENCH_REPORT_S", "0.25"))

    def factory(s: Settings, w: WorkerSettings, client: httpx.AsyncClient) -> Worker:
        worker = build_worker(s, w, client)
        worker.downloader = ThrottledDownloader(
            staging=worker.staging,
            audio=audio,
            duration_ms=duration_ms,
            first_byte_s=first_byte_s,
            rate_bytes_s=rate,
            report_s=report_s,
        )
        return worker

    return run_worker(settings, factory=factory)


if __name__ == "__main__":
    sys.exit(main())
