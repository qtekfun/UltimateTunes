# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""End-to-end suite (PLAN T20): pytest against the real containers of the test stack, over HTTP.

Every test here is marked `e2e` and skipped unless `UT_E2E=1`, so `make check` never needs
Docker. `tools/e2e/run.sh` (or the `e2e` workflow) brings the stack up, runs
`UT_E2E=1 uv run pytest tests/e2e`, then tears it down. Settings:

- `UT_E2E_URL` (default `http://127.0.0.1:$UT_E2E_PORT`, port 8044): where the api answers;
- `UT_E2E_PROJECT` (default `ut-e2e`): the Compose project, to stop and start the worker.

Each test uses its own songs of the fake catalog (search/fake.py), so the order does not matter;
the suite expects a fresh stack (run.sh starts from empty volumes).
"""

import os
from collections.abc import Callable, Iterator

import httpx
import pytest

from tests.e2e.stack import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    AdminPanel,
    Client,
    Compose,
    create_key,
    env_url,
    wait_until,
)

ENABLED = os.environ.get("UT_E2E") == "1"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "e2e: end-to-end test against the running stack (UT_E2E=1)")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    skip = pytest.mark.skip(reason="end-to-end: set UT_E2E=1 with the stack up (tools/e2e/run.sh)")
    for item in items:
        if item.get_closest_marker("e2e") is not None and not ENABLED:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def base_url() -> str:
    url = env_url().rstrip("/")

    def ready() -> bool | None:
        try:
            return httpx.get(f"{url}/readyz", timeout=3.0).status_code == 200 or None
        except httpx.TransportError:
            return None

    wait_until(ready, timeout_s=120.0, what=f"{url}/readyz")
    return url


@pytest.fixture(scope="session")
def compose() -> Compose:
    return Compose(os.environ.get("UT_E2E_PROJECT", "ut-e2e"))


@pytest.fixture(scope="session")
def admin_panel(base_url: str, compose: Compose) -> Iterator[AdminPanel]:
    compose.bootstrap_admin()
    panel = AdminPanel(base_url)
    panel.login(ADMIN_USERNAME, ADMIN_PASSWORD)
    yield panel
    panel.close()


UserFactory = Callable[[str], Client]


@pytest.fixture(scope="session")
def make_user(base_url: str, admin_panel: AdminPanel) -> Iterator[UserFactory]:
    """A new user (created in the admin panel) with a fresh API key for one device."""
    clients: list[Client] = []

    def make(username: str) -> Client:
        password = f"{username}-password-not-a-secret"
        admin_panel.create_user(username, password)
        client = Client(base_url, create_key(base_url, username, password, f"{username} e2e"))
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.close()
