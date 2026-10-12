# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The contract app's real lifespan runs once around the whole contract session; LRCLIB is
answered by respx around each contract module (lyrics of the invented library; no request
leaves the machine), and only there, so other test packages keep their own mocks."""

from collections.abc import Iterator
from pathlib import Path

import pytest
import respx
from starlette.testclient import TestClient

from tests.contract.harness import APP
from ultimatetunes.lyrics.lrclib import BASE_URL

LYRICS = Path(__file__).resolve().parents[1] / "lyrics" / "fixtures" / "lighthouse_keeper.json"


@pytest.fixture(scope="session", autouse=True)
def app_lifespan() -> Iterator[None]:
    """App startup before the first contract call; shutdown (closes the DB) after the last."""
    with TestClient(APP):
        yield


@pytest.fixture(scope="module", autouse=True)
def lrclib() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        router.get("/api/get").respond(200, content=LYRICS.read_bytes())
        yield router
