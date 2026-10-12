# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`FakeDownloader`: writes a short silent Ogg/Opus file into staging, slowly.

The audio is `assets/silence.opus` (2 s of generated silence, CC0, see `assets/README.md`), an
allowed archive format (SPEC section 11), so tagging and library tests downstream get a real
file. It is written in chunks with a pause between them, as `<video_id>.opus.part` renamed to
`<video_id>.opus` at the end, with the exact size announced from the first report, like the
real downloader, so streaming-while-downloading tests (T16) see a growing file.
`fail_after_bytes` makes it stop mid-download with `fail_code`, for failure tests.
"""

import math
from collections.abc import Awaitable, Callable
from importlib import resources

import anyio

from ultimatetunes.core.storage import StagingStore
from ultimatetunes.errors import WorkerErrorCode
from ultimatetunes.worker.downloader import (
    DownloadError,
    DownloadProgress,
    DownloadResult,
    ProgressCallback,
    check_video_id,
)

CONTENT_TYPE = "audio/ogg"
FORMAT_ID = "fake-opus"
DURATION_MS = 2000


def silence_opus() -> bytes:
    """The bundled silent Ogg/Opus file."""
    return (resources.files("ultimatetunes.worker") / "assets" / "silence.opus").read_bytes()


class FakeDownloader:
    def __init__(  # noqa: PLR0913 - keyword-only knobs of a test fake
        self,
        staging: StagingStore,
        *,
        chunks: int = 8,
        delay_s: float = 0.05,
        fail_after_bytes: int | None = None,
        fail_code: WorkerErrorCode = WorkerErrorCode.NETWORK_ERROR,
        sleep: Callable[[float], Awaitable[None]] = anyio.sleep,
    ) -> None:
        if chunks < 1:
            raise ValueError("at least one chunk")
        self._staging = staging
        self._audio = silence_opus()
        self._chunks = chunks
        self._delay_s = delay_s
        self._fail_after = fail_after_bytes
        self._fail_code = fail_code
        self._sleep = sleep
        self.downloads: list[str] = []

    async def download(
        self, video_id: str, job_dir: str, on_progress: ProgressCallback
    ) -> DownloadResult:
        check_video_id(video_id)
        self.downloads.append(video_id)
        final = f"{job_dir}/{video_id}.opus"
        part = f"{final}.part"
        total = len(self._audio)
        size = math.ceil(total / self._chunks)
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

        with self._staging.open_write(part) as out:
            while written < total:
                if self._fail_after is not None and written >= self._fail_after:
                    raise DownloadError(self._fail_code, "fake failure")
                chunk = self._audio[written : written + size]
                out.write(chunk)
                out.flush()
                written += len(chunk)
                await on_progress(report(finished=False))
                await self._sleep(self._delay_s)
        self._staging.rename(part, final)
        await on_progress(report(finished=True))
        return DownloadResult(final, FORMAT_ID, "opus", CONTENT_TYPE, total, DURATION_MS)
