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

# Query or form parameters that carry credentials (OpenSubsonic: apiKey, p, t, s).
_PARAM = re.compile(
    r"(?P<key>(?:^|[?&;\s])(?:apiKey|api_key|p|t|s|password|token|secret)=)(?P<value>[^&;\s\"']+)",
    re.IGNORECASE,
)
# Header-like or key/value pairs: "Authorization: Bearer x", "cookie=x", "password: x".
_PAIR = re.compile(
    r"(?P<key>\b(?:authorization|cookie|set-cookie|x-api-key|password|token|secret)\b"
    r"\s*[:=]\s*)(?P<value>(?:bearer\s+|basic\s+)?[^\s,;\"']+)",
    re.IGNORECASE,
)
_SECRET_KEY = re.compile(
    r"apikey|api_key|password|passwd|token|secret|cookie|authorization", re.IGNORECASE
)


def redact(text: str) -> str:
    """Hides credential values in free text (URLs, headers, key=value pairs)."""
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
