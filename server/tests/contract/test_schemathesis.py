# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""schemathesis against the app for the three contracts (PLAN T02 bootstrap; T19 extends it).

Generated requests (valid and invalid, `generation.mode = all`) hit the real app in-process.
Every response must conform to the contract: a documented status code, content type, headers
and body schema. `UT_CONTRACT_EXAMPLES` sets examples per operation (default 5 for
`make check`; `make contracts` runs more).

The app runs against a migrated database (authenticated calls reach it), and schemathesis drives
it through `_SessionLifespan`, which answers `lifespan` itself: the app's real lifespan runs once
for the whole module (`app_lifespan`), not around every generated call, so the database is not
closed after the first one.
"""

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import schemathesis
from hypothesis import HealthCheck, settings
from pydantic import SecretStr
from schemathesis.schemas import BaseSchema
from schemathesis.specs.openapi.checks import (
    content_type_conformance,
    response_headers_conformance,
    response_schema_conformance,
    status_code_conformance,
)
from starlette.testclient import TestClient
from starlette.types import ASGIApp, Receive, Scope, Send

from ultimatetunes.app import create_app
from ultimatetunes.db import migrate
from ultimatetunes.settings import Settings

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
OPENAPI = CONTRACTS / "openapi"
EXAMPLES = int(os.environ.get("UT_CONTRACT_EXAMPLES", "5"))
TOKEN = "contract-test-worker-token"
CHECKS = [
    status_code_conformance,
    content_type_conformance,
    response_headers_conformance,
    response_schema_conformance,
]

_ROOT = tempfile.TemporaryDirectory(prefix="ut-contract-")
for _name in ("data", "music", "staging"):
    (Path(_ROOT.name) / _name).mkdir()
_SETTINGS = Settings(
    data_dir=Path(_ROOT.name) / "data",
    music_dir=Path(_ROOT.name) / "music",
    staging_dir=Path(_ROOT.name) / "staging",
    migrations_dir=CONTRACTS / "db" / "migrations",
    worker_token=SecretStr(TOKEN),
)
_conn = migrate.connect(_SETTINGS.database_file)
try:
    migrate.migrate(_conn, _SETTINGS.migrations_dir)
finally:
    _conn.close()
APP = create_app(_SETTINGS)


class _SessionLifespan:
    """Forwards every HTTP call to the app and answers `lifespan` without forwarding it."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "lifespan":
            await self.app(scope, receive, send)
            return
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return


@pytest.fixture(scope="module", autouse=True)
def app_lifespan() -> Iterator[None]:
    """App startup before the first generated call; shutdown (closes the DB) after the last."""
    with TestClient(APP):
        yield


def load(name: str) -> BaseSchema:
    schema = schemathesis.openapi.from_path(OPENAPI / name)
    schema.app = _SessionLifespan(APP)
    return schema


opensubsonic = load("opensubsonic-subset.yaml")
ut_v1 = load("ut-v1.yaml")
internal = load("internal-worker.yaml")
SETTINGS = settings(
    max_examples=EXAMPLES,
    deadline=None,
    suppress_health_check=list(HealthCheck),
    derandomize=True,
)


@opensubsonic.parametrize()
@SETTINGS
def test_opensubsonic(case: Any) -> None:
    case.call_and_validate(checks=CHECKS)


@ut_v1.parametrize()
@SETTINGS
def test_ut_v1(case: Any) -> None:
    case.call_and_validate(checks=CHECKS)


@internal.parametrize()
@SETTINGS
def test_internal_worker_with_token(case: Any) -> None:
    case.call_and_validate(checks=CHECKS, headers={"Authorization": f"Bearer {TOKEN}"})


@internal.parametrize()
@SETTINGS
def test_internal_worker_without_token(case: Any) -> None:
    response = case.call_and_validate(checks=CHECKS)
    # 405: schemathesis also probes methods the path does not have.
    assert response.status_code in {401, 405}
