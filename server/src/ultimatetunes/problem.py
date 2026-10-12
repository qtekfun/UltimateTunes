# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""RFC 9457 problem responses for `/ut/v1` and `/internal/v1` (contracts/errors.md)."""

import json

from starlette.responses import Response

from ultimatetunes.errors import (
    MAPPING,
    PROBLEM_TYPE_BASE,
    InternalError,
    RetryLater,
    TunesError,
    spec_for,
)

PROBLEM_TYPE = "application/problem+json"


def problem_response(error: TunesError, instance: str) -> Response:
    spec = spec_for(error)
    status, code = spec.http_status, spec.problem_code
    if status is None or code is None:
        # Errors that only exist on /rest (e.g. token auth): never expected here.
        error, spec = InternalError(), MAPPING[InternalError]
        status, code = 500, "internal_error"
    body: dict[str, object] = {
        "type": PROBLEM_TYPE_BASE + code,
        "title": spec.title,
        "status": status,
        "detail": error.message,
        "instance": instance,
        "code": code,
    }
    headers: dict[str, str] = {}
    if isinstance(error, RetryLater):
        body["retryAfter"] = error.retry_after_s
        headers["Retry-After"] = str(error.retry_after_s)
    return Response(
        json.dumps(body, ensure_ascii=False),
        status_code=status,
        media_type=PROBLEM_TYPE,
        headers=headers,
    )
