# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixtures of the canary tests: fakes only (CLAUDE.md: never a real download or network)."""

from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from ultimatetunes.canary.checks import FAKE_PLAYLIST_ID, FAKE_QUERY, FAKE_VIDEO_ID, Targets
from ultimatetunes.core.storage import LocalStagingStore
from ultimatetunes.search.fake import FakeMusicCatalog
from ultimatetunes.worker.fake import FakeDownloader

Sleep = Callable[[float], Awaitable[None]]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def no_sleep(_seconds: float) -> None:
    return None


@pytest.fixture
def staging(tmp_path: Path) -> LocalStagingStore:
    root = tmp_path / "staging-store"
    root.mkdir()
    return LocalStagingStore(root)


@pytest.fixture
def catalog() -> FakeMusicCatalog:
    return FakeMusicCatalog()


@pytest.fixture
def downloader(staging: LocalStagingStore) -> FakeDownloader:
    return FakeDownloader(staging, chunks=3, sleep=no_sleep)


FAKE_TARGETS = Targets(FAKE_VIDEO_ID, FAKE_QUERY, FAKE_PLAYLIST_ID)
