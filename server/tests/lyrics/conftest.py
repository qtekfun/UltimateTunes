# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Lyrics fixtures: LRCLIB mocked with respx (no network)."""

from collections.abc import Iterator

import pytest
import respx

from ultimatetunes.lyrics.lrclib import BASE_URL


@pytest.fixture
def lrclib() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        yield router
