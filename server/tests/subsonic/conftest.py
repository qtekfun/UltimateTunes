# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixtures of the library tests (`harness.py`)."""

from collections.abc import Iterator

import pytest

from tests.library.harness import Harness, make_harness
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.settings import Settings


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def lib(settings: Settings, clock: FakeClock, monkeypatch: pytest.MonkeyPatch) -> Iterator[Harness]:
    # The app's startup scan is tested on its own (test_web.py).
    monkeypatch.setenv("UT_LIBRARY_SCAN_ON_START", "false")
    from ultimatetunes.library.web import library_settings  # noqa: PLC0415

    library_settings.cache_clear()
    yield from make_harness(settings, clock)
    library_settings.cache_clear()
