# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""FakeDownloader: a real Ogg/Opus file, written slowly as .part then renamed, failing on demand."""

import hashlib
from pathlib import Path

import pytest

from ultimatetunes.core.storage import LocalStagingStore
from ultimatetunes.errors import WorkerErrorCode
from ultimatetunes.settings import Settings
from ultimatetunes.worker.downloader import (
    DownloadError,
    DownloadProgress,
    build_downloader,
    check_video_id,
)
from ultimatetunes.worker.fake import FakeDownloader, silence_opus
from ultimatetunes.worker.ytdlp import YtDlpDownloader

pytestmark = pytest.mark.anyio

# assets/README.md: the hash of the committed CC0 silence.
SILENCE_SHA256 = "265dca7975cb22805625c6b38c2ba96edbac940885a89ff6d61a2add61e648d6"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def staging(tmp_path: Path) -> LocalStagingStore:
    return LocalStagingStore(tmp_path)


async def no_sleep(_seconds: float) -> None:
    return None


async def ignore(_p: DownloadProgress) -> None:
    return None


def test_the_asset_is_the_documented_ogg_opus_file() -> None:
    audio = silence_opus()
    assert hashlib.sha256(audio).hexdigest() == SILENCE_SHA256
    # Ogg page capture pattern, then the Opus identification header in the first page.
    assert audio.startswith(b"OggS")
    assert b"OpusHead" in audio[:64]
    assert b"OpusTags" in audio


async def test_downloads_grow_then_rename(staging: LocalStagingStore) -> None:
    downloader = FakeDownloader(staging, chunks=4, sleep=no_sleep)
    seen: list[DownloadProgress] = []
    sizes: list[int] = []

    async def progress(p: DownloadProgress) -> None:
        seen.append(p)
        if not p.finished:
            sizes.append(staging.size(p.part_path))
            assert p.downloaded_bytes == sizes[-1]

    result = await downloader.download("Qx7Lm2pZ0aB", "job1/1", progress)
    total = len(silence_opus())
    assert result.final_path == "job1/1/Qx7Lm2pZ0aB.opus"
    assert (result.ext, result.content_type, result.size_bytes) == ("opus", "audio/ogg", total)
    assert seen[0].part_path == "job1/1/Qx7Lm2pZ0aB.opus.part"
    assert all(p.final_path == result.final_path for p in seen)
    # The exact size is known from the first report, as the contract asks.
    assert {p.expected_size for p in seen} == {total}
    assert {(p.format_id, p.content_type, p.progressive) for p in seen} == {
        ("fake-opus", "audio/ogg", True)
    }
    assert sizes == sorted(sizes)
    assert len(sizes) == 4
    assert [p.finished for p in seen] == [False] * 4 + [True]
    assert seen[-1].downloaded_bytes == total
    with staging.open_read(result.final_path) as reader:
        assert reader.read() == silence_opus()
    assert not staging.exists("job1/1/Qx7Lm2pZ0aB.opus.part")
    assert downloader.downloads == ["Qx7Lm2pZ0aB"]


async def test_writes_slowly(staging: LocalStagingStore) -> None:
    pauses: list[float] = []

    async def sleep(seconds: float) -> None:
        pauses.append(seconds)

    await FakeDownloader(staging, chunks=3, delay_s=0.2, sleep=sleep).download(
        "Qx7Lm2pZ0aB", "job", ignore
    )
    assert pauses == [0.2, 0.2, 0.2]


async def test_fails_mid_download(staging: LocalStagingStore) -> None:
    downloader = FakeDownloader(
        staging,
        fail_after_bytes=1,
        fail_code=WorkerErrorCode.VIDEO_UNAVAILABLE,
        sleep=no_sleep,
    )
    with pytest.raises(DownloadError) as caught:
        await downloader.download("Qx7Lm2pZ0aB", "job1/1", ignore)
    assert caught.value.code == WorkerErrorCode.VIDEO_UNAVAILABLE
    assert not caught.value.retryable
    assert staging.exists("job1/1/Qx7Lm2pZ0aB.opus.part")


async def test_invalid_ids_never_reach_the_downloader(staging: LocalStagingStore) -> None:
    downloader = FakeDownloader(staging)
    with pytest.raises(DownloadError) as caught:
        await downloader.download("--exec=x", "job", ignore)
    assert caught.value.code == WorkerErrorCode.INVALID_VIDEO_ID
    assert not caught.value.retryable
    assert downloader.downloads == []
    assert check_video_id("Qx7Lm2pZ0aB") == "Qx7Lm2pZ0aB"
    with pytest.raises(ValueError, match="chunk"):
        FakeDownloader(staging, chunks=0)


async def test_build_downloader(settings: Settings, staging: LocalStagingStore) -> None:
    real = build_downloader(settings, staging)
    assert isinstance(real, YtDlpDownloader)
    fake = build_downloader(settings.model_copy(update={"fake_youtube": True}), staging)
    assert isinstance(fake, FakeDownloader)


def test_a_download_error_can_only_be_made_stricter() -> None:
    assert DownloadError(WorkerErrorCode.NETWORK_ERROR, "x").retryable
    assert not DownloadError(WorkerErrorCode.NETWORK_ERROR, "x", retryable=False).retryable
    assert not DownloadError(WorkerErrorCode.VIDEO_UNAVAILABLE, "x", retryable=True).retryable


def test_worker_error_codes_know_if_they_are_retryable() -> None:
    assert WorkerErrorCode.NETWORK_ERROR.retryable
    assert not WorkerErrorCode.CANCELLED.retryable
    assert not WorkerErrorCode.INVALID_VIDEO_ID.retryable
