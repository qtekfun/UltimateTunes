# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Radio tests run on the search tests' invented library (`tests/search/conftest.py`)."""

import pytest

from tests.search.conftest import library

__all__ = ["library"]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
