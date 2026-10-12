# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""RFC 9457 problem responses for `/ut/v1` and `/internal/v1` (contracts/errors.md)."""

import json

from starlette.responses import Response

from ultimatetunes.errors import (
    MAPPING,
    PROBLEM_TYPE_BASE,
    InternalError,
    RateLimited,
    TunesError,
    spec_for,
)

PROBLEM_TYPE = "application/problem+json"


def problem_response(error: TunesError, instance: str) -> Response:
    spec = spec_for(error)
    if spec.http_status is None or spec.problem_code is None:
        # Errors that only exist on /rest (e.g. token auth): never expected here.
        error, spec = InternalError(), MAPPING[InternalError]
    assert spec.http_status is not None  # noqa: S101 - narrowed above
    body: dict[str, object] = {
        "type": PROBLEM_TYPE_BASE + str(spec.problem_code),
        "title": spec.title,
        "status": spec.http_status,
        "detail": error.message,
        "instance": instance,
        "code": spec.problem_code,
    }
    headers: dict[str, str] = {}
    if isinstance(error, RateLimited):
        body["retryAfter"] = error.retry_after_s
        headers["Retry-After"] = str(error.retry_after_s)
    return Response(
        json.dumps(body, ensure_ascii=False),
        status_code=spec.http_status,
        media_type=PROBLEM_TYPE,
        headers=headers,
    )
