# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""schemathesis against the app for the three contracts (PLAN T02 bootstrap; T19 extends it).

Generated requests (valid and invalid, `generation.mode = all`) hit the real app in-process.
Every response must conform to the contract: a documented status code, content type, headers
and body schema. With the T02 stubs that means `501` with error 0 / `not_implemented` (or
`401 invalid_worker_token` on the internal API without the token). `UT_CONTRACT_EXAMPLES` sets
examples per operation (default 5 for `make check`; `make contracts` runs more).
"""

import os
import tempfile
from pathlib import Path
from typing import Any

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

from ultimatetunes.app import create_app
from ultimatetunes.settings import Settings

OPENAPI = Path(__file__).resolve().parents[3] / "contracts" / "openapi"
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
APP = create_app(
    Settings(
        data_dir=Path(_ROOT.name) / "data",
        music_dir=Path(_ROOT.name) / "music",
        staging_dir=Path(_ROOT.name) / "staging",
        worker_token=SecretStr(TOKEN),
    )
)


def load(name: str) -> BaseSchema:
    schema = schemathesis.openapi.from_path(OPENAPI / name)
    schema.app = APP
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
