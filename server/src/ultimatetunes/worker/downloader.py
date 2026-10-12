# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`Downloader`: fetch the audio of one video into the attempt's staging directory.

Shape from spike T03c: `download(video_id, job_dir, on_progress)` writes the raw audio
sequentially to `<job_dir>/<video_id>.<ext>.part`, never rewrites it, and renames it to
`<video_id>.<ext>` when complete (same inode, so a reader that has it open keeps reading).
`on_progress` mirrors the contract's `Progress` (contracts/openapi/internal-worker.yaml):
`part_path` and `final_path` from the first report on, the **exact** `expected_size` once known
(never an estimate), `format_id`, `content_type`, `progressive`, and `finished` at the end.
Failures are `DownloadError` with a worker error code from contracts/errors.md. Paths are
relative to the `StagingStore` root.
"""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from ultimatetunes.core.storage import StagingStore
from ultimatetunes.errors import WorkerErrorCode
from ultimatetunes.settings import Settings

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


@dataclass(frozen=True)
class DownloadProgress:
    downloaded_bytes: int
    expected_size: int | None
    part_path: str
    final_path: str
    finished: bool
    format_id: str
    content_type: str
    progressive: bool


@dataclass(frozen=True)
class DownloadResult:
    final_path: str
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
    """The id rule enforced right before any download (SECURITY.md). A bad id is a bug or
    tampering, never worth a retry: `invalid_video_id` is not retryable."""
    if not VIDEO_ID.fullmatch(video_id):
        raise DownloadError(WorkerErrorCode.INVALID_VIDEO_ID, "invalid video id")
    return video_id


class UnavailableDownloader:
    """Placeholder until T08 wires the real downloader."""

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
