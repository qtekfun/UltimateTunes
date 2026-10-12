# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""FakeDownloader: a valid WAV, written slowly as .part then renamed, failing on demand."""

import io
import wave
from pathlib import Path

import pytest

from ultimatetunes.core.storage import LocalStagingStore
from ultimatetunes.errors import WorkerErrorCode
from ultimatetunes.settings import Settings
from ultimatetunes.worker.downloader import (
    DownloadError,
    DownloadProgress,
    UnavailableDownloader,
    build_downloader,
)
from ultimatetunes.worker.fake import FakeDownloader, generate_wav

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def staging(tmp_path: Path) -> LocalStagingStore:
    return LocalStagingStore(tmp_path)


async def no_sleep(_seconds: float) -> None:
    return None


def test_generated_wav_is_valid() -> None:
    with wave.open(io.BytesIO(generate_wav(0.5)), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getframerate() == 8000
        assert audio.getnframes() == 4000


async def test_downloads_grow_then_rename(staging: LocalStagingStore) -> None:
    downloader = FakeDownloader(staging, duration_s=0.5, chunks=4, sleep=no_sleep)
    seen: list[DownloadProgress] = []
    sizes: list[int] = []

    async def progress(p: DownloadProgress) -> None:
        seen.append(p)
        if p.status == "downloading":
            sizes.append(staging.size(p.staging_path))

    result = await downloader.download("Qx7Lm2pZ0aB", "job1", progress)
    assert result.staging_path == "job1/Qx7Lm2pZ0aB.wav"
    assert seen[0].staging_path == "job1/Qx7Lm2pZ0aB.wav.part"
    assert sizes == sorted(sizes)
    assert len(sizes) == 4
    assert seen[-1].status == "finished"
    assert staging.size(result.staging_path) == result.size_bytes
    assert not staging.exists("job1/Qx7Lm2pZ0aB.wav.part")
    assert downloader.downloads == ["Qx7Lm2pZ0aB"]


async def test_fails_mid_download(staging: LocalStagingStore) -> None:
    downloader = FakeDownloader(
        staging,
        duration_s=0.5,
        fail_after_bytes=1,
        fail_code=WorkerErrorCode.VIDEO_UNAVAILABLE,
        sleep=no_sleep,
    )

    async def progress(_p: DownloadProgress) -> None:
        return None

    with pytest.raises(DownloadError) as caught:
        await downloader.download("Qx7Lm2pZ0aB", "job1", progress)
    assert caught.value.code == WorkerErrorCode.VIDEO_UNAVAILABLE
    assert not caught.value.retryable


async def test_invalid_ids_never_reach_the_downloader(staging: LocalStagingStore) -> None:
    async def progress(_p: DownloadProgress) -> None:
        return None

    with pytest.raises(DownloadError):
        await FakeDownloader(staging).download("--exec=x", "job", progress)
    with pytest.raises(ValueError, match="chunk"):
        FakeDownloader(staging, chunks=0)


async def test_build_downloader(settings: Settings, staging: LocalStagingStore) -> None:
    pending = build_downloader(settings, staging)
    assert isinstance(pending, UnavailableDownloader)

    async def progress(_p: DownloadProgress) -> None:
        return None

    with pytest.raises(DownloadError):
        await pending.download("Qx7Lm2pZ0aB", "job", progress)
    fake = build_downloader(settings.model_copy(update={"fake_youtube": True}), staging)
    assert isinstance(fake, FakeDownloader)


def test_worker_error_codes_know_if_they_are_retryable() -> None:
    assert WorkerErrorCode.NETWORK_ERROR.retryable
    assert not WorkerErrorCode.CANCELLED.retryable
