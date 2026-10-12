# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Secrets never reach the log output (CLAUDE.md, Security rules)."""

import io
import json
import logging
from collections.abc import Iterator

import pytest

from ultimatetunes.logging import (
    REDACTED,
    JsonFormatter,
    RedactingFilter,
    configure_logging,
    redact,
)

SECRET = "s3cr3t-Value_42"


@pytest.mark.parametrize(
    "text",
    [
        f"GET /rest/stream?id=1&apiKey={SECRET}&f=json",
        f"GET /rest/ping?u=ana&p={SECRET}",
        f"GET /rest/ping?u=ana&p=enc:{SECRET}",
        f"GET /rest/ping?u=ana&t={SECRET}&s=salt",
        f"Authorization: Bearer {SECRET}",
        f"cookie={SECRET}",
        f"password: {SECRET}",
        f"X-Api-Key: {SECRET}",
        f"token={SECRET}",
        f"apikey: {SECRET}",
        f"api_key: {SECRET}",
        f'{{"apiKey": "{SECRET}", "f": "json"}}',
        f"GET /x?next=%2Frest%3Fu%3Dana%26apiKey%3D{SECRET}%26f%3Djson",
        f"Cookie: a=1; session={SECRET}; csrf={SECRET}",
    ],
)
def test_redact_hides_credentials(text: str) -> None:
    out = redact(text)
    assert SECRET not in out
    assert REDACTED in out


def test_redact_keeps_harmless_text() -> None:
    text = "GET /rest/getAlbum?id=42&f=json 200"
    assert redact(text) == text


@pytest.fixture
def capture() -> Iterator[tuple[logging.Logger, io.StringIO]]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactingFilter())
    logger = logging.getLogger("test.redaction")
    logger.handlers[:] = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    yield logger, stream
    logger.handlers.clear()


def test_secrets_in_args_are_redacted(capture: tuple[logging.Logger, io.StringIO]) -> None:
    logger, stream = capture
    logger.info("request %s", f"/rest/stream?apiKey={SECRET}")
    logger.info("headers %s", {"Authorization": SECRET, "Accept": "audio/*"})
    logger.info("pair %s %s", "x", [f"password={SECRET}"])
    output = stream.getvalue()
    assert SECRET not in output
    assert "audio/*" in output


def test_secrets_in_exceptions_are_redacted(capture: tuple[logging.Logger, io.StringIO]) -> None:
    logger, stream = capture
    try:
        int(f"bad url ?apiKey={SECRET}")
    except ValueError:
        logger.exception("failed")
    entry = json.loads(stream.getvalue())
    assert SECRET not in entry["exception"]
    assert entry["level"] == "ERROR"


def test_mapping_args_are_redacted(capture: tuple[logging.Logger, io.StringIO]) -> None:
    logger, stream = capture
    logger.info("user %(user)s key %(apiKey)s", {"user": "ana", "apiKey": SECRET})
    entry = json.loads(stream.getvalue())
    assert SECRET not in entry["message"]
    assert "ana" in entry["message"]


def test_configure_logging_routes_uvicorn_access_through_redaction(
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = logging.getLogger()
    saved = root.handlers[:], root.level
    try:
        configure_logging("INFO")
        logging.getLogger("uvicorn.access").info(
            '%s - "%s %s HTTP/%s" %d', "10.0.0.1", "GET", f"/rest/ping?apiKey={SECRET}", "1.1", 200
        )
        line = capsys.readouterr().out.strip()
    finally:
        root.handlers[:], level = saved
        root.setLevel(level)
    entry = json.loads(line)
    assert entry["logger"] == "uvicorn.access"
    assert SECRET not in line
