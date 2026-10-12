# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Typed errors and the **one** table that maps them to wire formats (contracts/errors.md).

Handlers raise a `TunesError` subclass; they never build envelopes or status codes by hand.
`spec_for(error)` gives the OpenSubsonic code, the HTTP status on `/ut/v1` and `/internal/v1`,
and the RFC 9457 problem `code`. Subclasses defined elsewhere (e.g. a catalog-specific
`NotFound`) inherit the mapping of their nearest mapped ancestor.

Naming: contracts/errors.md calls the stub error `NotImplemented`. That name is a Python
builtin constant, so the class is `FeatureNotImplemented`; its codes are unchanged.
"""

# The class names are the contract (contracts/errors.md), not "...Error" (ruff N818).
# ruff: noqa: N818

from dataclasses import dataclass
from enum import StrEnum

PROBLEM_TYPE_BASE = "https://github.com/qtekfun/UltimateTunes/blob/master/contracts/errors.md#"


class TunesError(Exception):
    """Base of every expected failure. `message` is safe to show to clients (no secrets)."""

    default_message = "Error"

    def __init__(self, message: str | None = None, *, help_url: str | None = None) -> None:
        self.message = message or self.default_message
        self.help_url = help_url
        super().__init__(self.message)


class MissingParameter(TunesError):
    default_message = "Required parameter is missing"


class InvalidParameter(TunesError):
    default_message = "Invalid parameter"


class InvalidId(TunesError):
    default_message = "Invalid id"


class ClientTooOld(TunesError):
    default_message = "Incompatible protocol version: the client must upgrade"


class ServerTooOld(TunesError):
    default_message = "Incompatible protocol version: the server must upgrade"


class AuthenticationRequired(TunesError):
    default_message = "Authentication required"


class AuthenticationFailed(TunesError):
    default_message = "Wrong username or password"


class TokenAuthNotSupported(TunesError):
    default_message = "Token authentication is not supported, use an API key"


class ConflictingAuth(TunesError):
    default_message = "Multiple conflicting authentication mechanisms provided"


class InvalidApiKey(TunesError):
    default_message = "Invalid API key"


class AccountDisabled(TunesError):
    default_message = "Account disabled"


class Forbidden(TunesError):
    default_message = "Not allowed"


class NotFound(TunesError):
    default_message = "Not found"


class Conflict(TunesError):
    default_message = "Conflict with the current state"


class FeatureDisabled(TunesError):
    default_message = "Feature disabled"


class UnsupportedUrl(TunesError):
    default_message = "Unsupported URL"


class PayloadTooLarge(TunesError):
    default_message = "Payload too large"


class RateLimited(TunesError):
    default_message = "Too many requests"

    def __init__(self, retry_after_s: int, message: str | None = None) -> None:
        self.retry_after_s = max(1, retry_after_s)
        super().__init__(message or f"Too many requests, retry in {self.retry_after_s} seconds")


class UpstreamUnavailable(TunesError):
    default_message = "Upstream service unavailable"


class DownloadFailed(TunesError):
    default_message = "Download failed"


class FeatureNotImplemented(TunesError):
    """`NotImplemented` in contracts/errors.md: router stubs (PLAN T02)."""

    default_message = "Not implemented"


class InternalError(TunesError):
    default_message = "Internal error"


class InvalidWorkerToken(TunesError):
    default_message = "Bearer token missing or wrong"


class LeaseLost(TunesError):
    default_message = "The lease is not the job's current lease"


class InvalidStateTransition(TunesError):
    default_message = "Transition not allowed by the job state machine"


class PathRejected(TunesError):
    default_message = "Path rejected"


@dataclass(frozen=True)
class ErrorSpec:
    """How one error type appears on the wire. `http_status`/`problem_code` are None where
    errors.md has "—" (the error cannot happen on `/ut/v1` or `/internal/v1`)."""

    subsonic_code: int
    http_status: int | None
    problem_code: str | None
    title: str
    subsonic_http_status: int = 200


# contracts/errors.md, "Mapping". The only place where codes and statuses are decided.
MAPPING: dict[type[TunesError], ErrorSpec] = {
    MissingParameter: ErrorSpec(10, 400, "missing_parameter", "Missing parameter"),
    InvalidParameter: ErrorSpec(0, 400, "invalid_parameter", "Invalid parameter"),
    InvalidId: ErrorSpec(70, 400, "invalid_id", "Invalid id"),
    ClientTooOld: ErrorSpec(20, None, None, "Client too old"),
    ServerTooOld: ErrorSpec(30, None, None, "Server too old"),
    AuthenticationRequired: ErrorSpec(
        10, 401, "authentication_required", "Authentication required"
    ),
    AuthenticationFailed: ErrorSpec(40, 401, "authentication_failed", "Authentication failed"),
    TokenAuthNotSupported: ErrorSpec(42, None, None, "Token authentication not supported"),
    ConflictingAuth: ErrorSpec(43, 400, "conflicting_auth", "Conflicting authentication"),
    InvalidApiKey: ErrorSpec(44, 401, "invalid_api_key", "Invalid API key"),
    AccountDisabled: ErrorSpec(50, 403, "account_disabled", "Account disabled"),
    Forbidden: ErrorSpec(50, 403, "forbidden", "Forbidden"),
    NotFound: ErrorSpec(70, 404, "not_found", "Not found"),
    Conflict: ErrorSpec(0, 409, "conflict", "Conflict"),
    FeatureDisabled: ErrorSpec(0, 409, "feature_disabled", "Feature disabled"),
    UnsupportedUrl: ErrorSpec(0, 400, "unsupported_url", "Unsupported URL"),
    PayloadTooLarge: ErrorSpec(0, 413, "payload_too_large", "Payload too large"),
    RateLimited: ErrorSpec(0, 429, "rate_limited", "Rate limited", subsonic_http_status=429),
    UpstreamUnavailable: ErrorSpec(0, 502, "upstream_unavailable", "Upstream unavailable"),
    DownloadFailed: ErrorSpec(0, 502, "download_failed", "Download failed"),
    FeatureNotImplemented: ErrorSpec(
        0, 501, "not_implemented", "Not implemented", subsonic_http_status=501
    ),
    InternalError: ErrorSpec(0, 500, "internal_error", "Internal error"),
    InvalidWorkerToken: ErrorSpec(0, 401, "invalid_worker_token", "Invalid worker token"),
    LeaseLost: ErrorSpec(0, 409, "lease_lost", "Lease lost"),
    InvalidStateTransition: ErrorSpec(
        0, 409, "invalid_state_transition", "Invalid state transition"
    ),
    PathRejected: ErrorSpec(0, 422, "path_rejected", "Path rejected"),
}


def spec_for(error: TunesError) -> ErrorSpec:
    """The mapping of the nearest mapped class in the error's MRO (InternalError if none)."""
    for cls in type(error).__mro__:
        spec = MAPPING.get(cls)
        if spec is not None:
            return spec
    return MAPPING[InternalError]


class WorkerErrorCode(StrEnum):
    """Job failure codes (contracts/errors.md, "Worker error codes")."""

    VIDEO_UNAVAILABLE = "video_unavailable"
    FORMAT_UNAVAILABLE = "format_unavailable"
    EXTRACTOR_ERROR = "extractor_error"
    NETWORK_ERROR = "network_error"
    RATE_LIMITED_UPSTREAM = "rate_limited_upstream"
    TAGGING_FAILED = "tagging_failed"
    STORAGE_ERROR = "storage_error"
    CANCELLED = "cancelled"
    LEASE_EXPIRED = "lease_expired"
    INTERNAL_ERROR = "internal_error"

    @property
    def retryable(self) -> bool:
        return self not in _NOT_RETRYABLE


_NOT_RETRYABLE = frozenset(
    {
        WorkerErrorCode.VIDEO_UNAVAILABLE,
        WorkerErrorCode.FORMAT_UNAVAILABLE,
        WorkerErrorCode.CANCELLED,
    }
)
