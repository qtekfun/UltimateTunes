# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The single mapping table matches contracts/errors.md."""

import json
import re
from pathlib import Path

from ultimatetunes import errors
from ultimatetunes.errors import (
    MAPPING,
    InternalError,
    NotFound,
    RateLimited,
    TokenAuthNotSupported,
    TunesError,
    spec_for,
)
from ultimatetunes.problem import problem_response

ERRORS_MD = Path(__file__).resolve().parents[2] / "contracts" / "errors.md"
ROW = re.compile(r"^\| `(\w+)` \|[^|]*\| ([^|]+) \| ([^|]+) \| ([^|]+) \|$")


def contract_rows() -> dict[str, tuple[str, str, str]]:
    rows = {}
    for line in ERRORS_MD.read_text(encoding="utf-8").splitlines():
        match = ROW.match(line.strip())
        if match:
            rows[match[1]] = (match[2].strip(), match[3].strip(), match[4].strip())
    return rows


def test_mapping_matches_the_contract_table() -> None:
    rows = contract_rows()
    renamed = {"NotImplemented": "FeatureNotImplemented"}
    assert len(rows) == len(MAPPING) == 26
    for name, (os_code, http, problem) in rows.items():
        spec = MAPPING[getattr(errors, renamed.get(name, name))]
        if os_code != "—":  # worker-only errors never reach /rest
            assert os_code.split()[0] == str(spec.subsonic_code), name
        assert http == ("—" if spec.http_status is None else str(spec.http_status)), name
        assert problem == ("—" if spec.problem_code is None else f"`{spec.problem_code}`"), name


def test_subclasses_inherit_and_unknown_errors_are_internal() -> None:
    class CatalogGone(NotFound):
        pass

    assert spec_for(CatalogGone()).problem_code == "not_found"
    assert spec_for(TunesError()) == MAPPING[InternalError]


def test_problem_body_and_rate_limit_header() -> None:
    response = problem_response(RateLimited(12), "/ut/v1/search")
    body = json.loads(bytes(response.body))
    assert response.status_code == 429
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["Retry-After"] == "12"
    assert body["code"] == "rate_limited"
    assert body["retryAfter"] == 12
    assert body["type"].endswith("errors.md#rate_limited")
    assert body["instance"] == "/ut/v1/search"


def test_rest_only_errors_become_internal_problems() -> None:
    response = problem_response(TokenAuthNotSupported(), "/ut/v1/me")
    assert response.status_code == 500
    assert json.loads(bytes(response.body))["code"] == "internal_error"
