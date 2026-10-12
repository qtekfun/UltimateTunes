# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`Downloader`: fetch the audio of one video into the job's staging directory.

Shape from spike T03c: `download(video_id, job_dir, on_progress)` writes to
`<job_dir>/<video_id>.<ext>.part` and renames it to `<video_id>.<ext>` when complete (yt-dlp's
own behaviour, which the api relies on to stream the growing file). `on_progress` gets the
relative staging path from the first report on. Failures are `DownloadError` with a worker
error code from contracts/errors.md. Paths are relative to the `StagingStore` root.
"""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from ultimatetunes.core.storage import StagingStore
from ultimatetunes.errors import WorkerErrorCode
from ultimatetunes.settings import Settings

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


@dataclass(frozen=True)
class DownloadProgress:
    status: Literal["downloading", "finished"]
    downloaded_bytes: int
    total_bytes: int | None
    staging_path: str
    content_type: str


@dataclass(frozen=True)
class DownloadResult:
    staging_path: str
    format_id: str
    ext: str
    content_type: str
    size_bytes: int
    duration_ms: int | None


class DownloadError(Exception):
    def __init__(self, code: WorkerErrorCode, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")

    @property
    def retryable(self) -> bool:
        return self.code.retryable


ProgressCallback = Callable[[DownloadProgress], Awaitable[None]]


class Downloader(Protocol):
    async def download(
        self, video_id: str, job_dir: str, on_progress: ProgressCallback
    ) -> DownloadResult: ...


def check_video_id(video_id: str) -> str:
    """The id rule enforced right before any download (SECURITY.md)."""
    if not VIDEO_ID.fullmatch(video_id):
        raise DownloadError(WorkerErrorCode.INTERNAL_ERROR, "invalid video id")
    return video_id


class UnavailableDownloader:
    """Placeholder until T08 wires yt-dlp."""

    async def download(
        self, video_id: str, job_dir: str, on_progress: ProgressCallback
    ) -> DownloadResult:
        raise DownloadError(WorkerErrorCode.INTERNAL_ERROR, "downloader not implemented yet")


def build_downloader(settings: Settings, staging: StagingStore) -> Downloader:
    """The worker's downloader: the fake with `UT_FAKE_YOUTUBE=true` (test stack)."""
    if settings.fake_youtube:
        from ultimatetunes.worker.fake import FakeDownloader  # noqa: PLC0415

        return FakeDownloader(staging)
    return UnavailableDownloader()
