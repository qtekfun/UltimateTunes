# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixtures of the streaming tests (`harness.py`)."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from tests.streaming.harness import Live, serve
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.db import Database
from ultimatetunes.settings import Settings


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def stream_settings(
    settings: Settings, db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Settings:
    """Settings on the migrated test database, with a quick poll and no background sweep."""
    monkeypatch.setenv("UT_STREAM_POLL_INTERVAL_S", "0.05")
    monkeypatch.setenv("UT_STAGING_SWEEP_INTERVAL_S", "0")
    monkeypatch.setenv("UT_LIBRARY_SCAN_ON_START", "false")
    return settings.model_copy(update={"database_path": tmp_path / "data" / "ut.db"})


@pytest.fixture
async def live(stream_settings: Settings, clock: FakeClock) -> AsyncIterator[Live]:
    async with serve(stream_settings, clock) as running:
        yield running
