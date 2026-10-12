# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""schemathesis against the real app for the three contracts (PLAN T02 bootstrap, T19).

Generated requests (valid and invalid, `generation.mode = all`) hit the real app in-process
(`harness.py`: migrated database, invented library, fake YouTube). Every response must conform
to the contract: a documented status code, content type, headers and body schema.

Each contract runs twice:
- **authenticated**: a real API key of a real user (`apiKey` for OpenSubsonic, `X-Api-Key` for
  ut-v1, the bearer token for the internal worker API), so every implemented endpoint is checked
  past authentication, in JSON and XML (`f` is generated from its enum);
- **anonymous**: whatever schemathesis generates for the credentials, so the error paths
  (errors 10, 40, 42, 43, 44; 401 problems) are checked too.

`UT_CONTRACT_EXAMPLES` sets examples per operation (default 5 for `make check`; `make
contracts` runs more). `derandomize=True` keeps every run identical (deterministic CI).
"""

import os
import re
from typing import Any

import schemathesis
from hypothesis import HealthCheck, settings
from schemathesis.schemas import BaseSchema
from schemathesis.specs.openapi.checks import (
    content_type_conformance,
    response_headers_conformance,
    response_schema_conformance,
    status_code_conformance,
)

from tests.contract.harness import API_KEY, APP, OPENAPI, TOKEN, SessionLifespan

EXAMPLES = int(os.environ.get("UT_CONTRACT_EXAMPLES", "5"))
CHECKS = [
    status_code_conformance,
    content_type_conformance,
    response_headers_conformance,
    response_schema_conformance,
]
# OpenSubsonic credentials: the key replaces every generated one (`apiKey` with `u`/`p`/`t`/`s`
# would be error 43, by design).
CREDENTIALS = ("apiKey", "u", "p", "t", "s")
# Authentication failures (contracts/errors.md): none may answer a request with a valid key.
# (10 also means "required parameter missing", which generated requests do get.)
AUTH_ERRORS = {40, 41, 42, 43, 44}
KEY_PROBLEMS = {"authentication_required", "invalid_api_key", "conflicting_auth"}
AUTH_CODE = re.compile(r'<error[^>]*\scode="(\d+)"')


def load(name: str) -> BaseSchema:
    schema = schemathesis.openapi.from_path(OPENAPI / name)
    schema.app = SessionLifespan(APP)
    return schema


class SubsonicKey:
    """`apiKey` of the contract user, always in the query: a generated POST may carry a body
    of another content type, which the server does not read (credentials included). Generated
    credentials are dropped from the query and the form body."""

    def get(self, case: Any, ctx: schemathesis.AuthContext) -> str:
        return API_KEY

    def set(self, case: Any, data: str, ctx: schemathesis.AuthContext) -> None:
        if isinstance(case.body, dict):
            case.body = {k: v for k, v in case.body.items() if k not in CREDENTIALS}
        query = {k: v for k, v in (case.query or {}).items() if k not in CREDENTIALS}
        case.query = {**query, "apiKey": data}


class HeaderKey:
    """`X-Api-Key` of the contract user (ut-v1); a generated `apiKey` query is dropped, since
    the header and the query together are refused."""

    def get(self, case: Any, ctx: schemathesis.AuthContext) -> str:
        return API_KEY

    def set(self, case: Any, data: str, ctx: schemathesis.AuthContext) -> None:
        case.query = {k: v for k, v in (case.query or {}).items() if k != "apiKey"}
        case.headers = {**(case.headers or {}), "X-Api-Key": data}


opensubsonic = load("opensubsonic-subset.yaml")
ut_v1 = load("ut-v1.yaml")
internal = load("internal-worker.yaml")
SETTINGS = settings(
    max_examples=EXAMPLES,
    deadline=None,
    suppress_health_check=list(HealthCheck),
    derandomize=True,
)


def subsonic_error(response: Any) -> int | None:
    """The OpenSubsonic error code of a JSON or XML envelope, None when it is not a failure."""
    # schemathesis keeps every header as a list of values.
    content_type = (response.headers.get("content-type") or [""])[0]
    if content_type.startswith("application/json"):
        body = response.json().get("subsonic-response", {})
        error = body.get("error") if isinstance(body, dict) else None
        return int(error["code"]) if isinstance(error, dict) else None
    if content_type.startswith("application/xml"):
        found = AUTH_CODE.search(response.text)
        return int(found.group(1)) if found else None
    return None


@opensubsonic.auth(SubsonicKey)
@opensubsonic.parametrize()
@SETTINGS
def test_opensubsonic_authenticated(case: Any) -> None:
    response = case.call_and_validate(checks=CHECKS)
    # The key is valid: whatever else was generated, authentication itself never fails.
    assert subsonic_error(response) not in AUTH_ERRORS, response.text


@opensubsonic.parametrize()
@SETTINGS
def test_opensubsonic_anonymous(case: Any) -> None:
    case.call_and_validate(checks=CHECKS)


@ut_v1.auth(HeaderKey)
@ut_v1.parametrize()
@SETTINGS
def test_ut_v1_authenticated(case: Any) -> None:
    response = case.call_and_validate(checks=CHECKS)
    # `POST /ut/v1/keys` checks the generated username and password (`authentication_failed`);
    # the key itself is never refused.
    if response.status_code == 401 and "X-Api-Key" in response.request.headers:
        assert response.json()["code"] not in KEY_PROBLEMS, response.text


@ut_v1.parametrize()
@SETTINGS
def test_ut_v1_anonymous(case: Any) -> None:
    case.call_and_validate(checks=CHECKS)


@internal.parametrize()
@SETTINGS
def test_internal_worker_with_token(case: Any) -> None:
    response = case.call_and_validate(checks=CHECKS, headers={"Authorization": f"Bearer {TOKEN}"})
    # schemathesis also sends some cases with the credentials removed on purpose (401 expected).
    if "Authorization" in response.request.headers:
        assert response.status_code != 401, response.text


@internal.parametrize()
@SETTINGS
def test_internal_worker_without_token(case: Any) -> None:
    response = case.call_and_validate(checks=CHECKS)
    # 405: schemathesis also probes methods the path does not have.
    assert response.status_code in {401, 405}
