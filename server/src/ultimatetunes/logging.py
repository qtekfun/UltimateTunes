# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""JSON logs to stdout with secrets redacted before anything is written (SECURITY.md)."""

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any, override

REDACTED = "[REDACTED]"
# Third-party loggers that would log full outbound URLs below WARNING.
QUIET_LOGGERS = ("httpx", "httpcore")

# Query or form parameters that carry credentials (OpenSubsonic: apiKey, p, t, s), also URL-encoded.
_PARAM = re.compile(
    r"(?P<key>(?:^|[?&;\s]|%26|%3F)(?:apiKey|api_key|p|t|s|password|token|secret)(?:=|%3D))"
    r"(?P<value>[^&;\s\"'%]+(?:%(?!26)[0-9A-F]{2}[^&;\s\"'%]*)*)",
    re.IGNORECASE,
)
# Key/value pairs in headers, JSON or free text: "Authorization: Bearer x", '"apiKey": "x"'.
# A value _PARAM already redacted is skipped, so "apiKey=[REDACTED]&f=json" keeps "&f=json".
_PAIR = re.compile(
    r"(?P<key>\b(?:authorization|x-api-key|api[-_]?key|password|passwd|token|secret)\b"
    r"[\"']?\s*[:=]\s*[\"']?)(?!\[REDACTED\])"
    r"(?P<value>(?:bearer\s+|basic\s+)?[^\s,;\"']+)",
    re.IGNORECASE,
)
# A cookie header holds several cookies: hide all of them, up to the end of the line.
_COOKIE = re.compile(
    r"(?P<key>\b(?:set-)?cookie[\"']?\s*[:=]\s*)(?P<value>[^\r\n]+)", re.IGNORECASE
)
# An API key anywhere, whatever surrounds it (contracts/ids.md: `utk_` + 43 base64url chars).
_API_KEY = re.compile(r"utk_[A-Za-z0-9_-]{43}")
# An ntfy access token anywhere (`tk_` + letters and digits, 29 today; `UT_NOTIFY_TOKEN`).
_NTFY_TOKEN = re.compile(r"\btk_[A-Za-z0-9]{20,}")
# A Bearer or Basic value after an `authorization` name in any shape: a header line, a dict or
# a header tuple (`(b'authorization', b'Bearer x')`).
_AUTH_HEADER = re.compile(
    r"(?P<key>\bauthorization\b[^\r\n]{0,16}?\b(?:bearer|basic)\s+)(?!\[REDACTED\])"
    r"(?P<value>[^\s,;\"')\]}]+)",
    re.IGNORECASE,
)
_SECRET_KEY = re.compile(
    r"apikey|api_key|password|passwd|token|secret|cookie|authorization", re.IGNORECASE
)


def redact(text: str) -> str:
    """Hides credential values in free text (URLs, headers, JSON, key=value pairs)."""
    text = _API_KEY.sub(REDACTED, text)
    text = _NTFY_TOKEN.sub(REDACTED, text)
    text = _AUTH_HEADER.sub(lambda m: m.group("key") + REDACTED, text)
    text = _COOKIE.sub(lambda m: m.group("key") + REDACTED, text)
    text = _PARAM.sub(lambda m: m.group("key") + REDACTED, text)
    return _PAIR.sub(lambda m: m.group("key") + REDACTED, text)


def _redact_value(value: object) -> object:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {
            k: REDACTED if isinstance(k, str) and _SECRET_KEY.search(k) else _redact_value(v)
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return type(value)(_redact_value(v) for v in value)
    return value


class RedactingFilter(logging.Filter):
    """Rewrites the message and its arguments so no handler ever sees a secret."""

    @override
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.msg))
        if isinstance(record.args, dict):
            record.args = _redact_value(record.args)  # type: ignore[assignment]
        elif record.args:
            record.args = tuple(_redact_value(a) for a in record.args)
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line: time, level, logger, message, and exception if any."""

    @override
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        if record.exc_info:
            entry["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(entry, ensure_ascii=False)


def configure_logging(level: str) -> None:
    """Routes the root logger and uvicorn's loggers through one redacting JSON handler."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True
    # httpx logs every outbound request URL at INFO: notification targets (an ntfy topic is a
    # secret) and webhook paths would land in the logs. Their warnings still do (T22).
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(max(logging.WARNING, logging.getLevelName(level)))
