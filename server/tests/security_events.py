# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading the structured security events a test produced (`core/security_log.py`)."""

import logging
from collections.abc import Callable
from typing import Any

import pytest

from ultimatetunes.logging import FIELDS_ATTR, JsonFormatter, RedactingFilter

Events = Callable[..., list[dict[str, Any]]]


def fields_of(record: logging.LogRecord) -> dict[str, Any] | None:
    fields = getattr(record, FIELDS_ATTR, None)
    return fields if isinstance(fields, dict) else None


def collect(caplog: pytest.LogCaptureFixture, name: str | None = None) -> list[dict[str, Any]]:
    """The fields of every event (of `name`, when given) logged so far."""
    found = (fields_of(record) for record in caplog.records)
    return [f for f in found if f is not None and (name is None or f["event"] == name)]


def rendered(caplog: pytest.LogCaptureFixture) -> str:
    """Every captured record as the production handler writes it (filter + JSON)."""
    formatter, redacting = JsonFormatter(), RedactingFilter()
    lines = []
    for record in caplog.records:
        redacting.filter(record)
        lines.append(formatter.format(record))
    return "\n".join(lines)


@pytest.fixture
def events(caplog: pytest.LogCaptureFixture) -> Events:
    """`events()` or `events("auth.failure")`: the fields of the security events so far."""
    caplog.set_level(logging.INFO)
    return lambda name=None: collect(caplog, name)
