# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`FakeDownloader`: writes a short generated audio file into staging, slowly.

The audio is a valid PCM WAV (a quiet sine), generated in-process with the standard library:
no ffmpeg, no network, no fixture to commit. It is written in chunks with a pause between
them, as `<video_id>.wav.part` renamed to `<video_id>.wav` at the end, like yt-dlp, so
streaming-while-downloading tests (T16) see a growing file. `fail_after_bytes` makes it stop
mid-download with `fail_code`, for failure tests.
"""

import io
import math
import struct
import wave
from collections.abc import Awaitable, Callable

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

CONTENT_TYPE = "audio/wav"


def generate_wav(
    duration_s: float = 2.0, *, sample_rate: int = 8000, freq_hz: float = 440.0
) -> bytes:
    """Mono 16-bit PCM WAV with a sine at a tenth of full scale."""
    frames = int(duration_s * sample_rate)
    amplitude = 3276
    pcm = b"".join(
        struct.pack("<h", int(amplitude * math.sin(2 * math.pi * freq_hz * i / sample_rate)))
        for i in range(frames)
    )
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        out.writeframes(pcm)
    return buffer.getvalue()


class FakeDownloader:
    def __init__(  # noqa: PLR0913 - keyword-only knobs of a test fake
        self,
        staging: StagingStore,
        *,
        duration_s: float = 2.0,
        chunks: int = 8,
        delay_s: float = 0.05,
        fail_after_bytes: int | None = None,
        fail_code: WorkerErrorCode = WorkerErrorCode.NETWORK_ERROR,
        sleep: Callable[[float], Awaitable[None]] = anyio.sleep,
    ) -> None:
        if chunks < 1:
            raise ValueError("at least one chunk")
        self._staging = staging
        self._audio = generate_wav(duration_s)
        self._duration_ms = int(duration_s * 1000)
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
        final = f"{job_dir}/{video_id}.wav"
        part = f"{final}.part"
        total = len(self._audio)
        size = math.ceil(total / self._chunks)
        written = 0
        with self._staging.open_write(part) as out:
            while written < total:
                if self._fail_after is not None and written >= self._fail_after:
                    raise DownloadError(self._fail_code, "fake failure")
                chunk = self._audio[written : written + size]
                out.write(chunk)
                out.flush()
                written += len(chunk)
                await on_progress(
                    DownloadProgress("downloading", written, total, part, CONTENT_TYPE)
                )
                await self._sleep(self._delay_s)
        self._staging.rename(part, final)
        await on_progress(DownloadProgress("finished", total, total, final, CONTENT_TYPE))
        return DownloadResult(final, "fake-wav", "wav", CONTENT_TYPE, total, self._duration_ms)
