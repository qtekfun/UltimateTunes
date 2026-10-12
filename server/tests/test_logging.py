# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Secrets never reach the log output (CLAUDE.md, Security rules)."""

import base64
import io
import json
import logging
import secrets
import string
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


API_KEY = "utk_" + "Ab3_-" * 8 + "xyz"


@pytest.mark.parametrize(
    "text",
    [
        f"key {API_KEY} created",
        f"/rest/stream?id=1&q={API_KEY}",
        f'{{"note": "{API_KEY}"}}',
        f"path=/x/{API_KEY}/y",
    ],
)
def test_api_keys_are_redacted_anywhere(text: str) -> None:
    assert len(API_KEY) == 47
    out = redact(text)
    assert API_KEY not in out
    assert "utk_" not in out
    assert REDACTED in out


def test_short_utk_strings_are_not_keys() -> None:
    assert redact("utk_short") == "utk_short"


def test_redact_keeps_the_parameters_after_a_redacted_one() -> None:
    text = f"GET /rest/stream?id=1&apiKey={SECRET}&f=json 200"
    assert redact(text) == f"GET /rest/stream?id=1&apiKey={REDACTED}&f=json 200"


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


@pytest.mark.parametrize("level", ["DEBUG", "INFO", "ERROR"])
def test_outbound_request_urls_are_not_logged(
    capsys: pytest.CaptureFixture[str], level: str
) -> None:
    """httpx logs each request URL at INFO (an ntfy topic, a webhook path): kept out (T22)."""
    root = logging.getLogger()
    saved = root.handlers[:], root.level
    quiet = {name: logging.getLogger(name).level for name in ("httpx", "httpcore")}
    try:
        configure_logging(level)
        logging.getLogger("httpx").info('HTTP Request: POST https://ntfy.example.net/topic-1 "200"')
        logging.getLogger("httpcore").debug("connect_tcp.started host='ntfy.example.net'")
        logging.getLogger("httpx").error("transport failed")
        out = capsys.readouterr().out
    finally:
        root.handlers[:], root_level = saved
        root.setLevel(root_level)
        for name, previous in quiet.items():
            logging.getLogger(name).setLevel(previous)
    assert "topic-1" not in out
    assert "connect_tcp" not in out
    assert "transport failed" in out


def _ntfy_token() -> str:
    """Shaped like an ntfy access token, made at run time (no secret-looking literal here)."""
    alphabet = string.ascii_lowercase + string.digits
    return "tk_" + "".join(secrets.choice(alphabet) for _ in range(29))


@pytest.mark.parametrize(
    "template",
    [
        "token {} created",
        "Authorization: Bearer {}",
        '{{"note": "{}"}}',
        "UT_NOTIFY_TOKEN={}",
    ],
)
def test_ntfy_tokens_are_redacted_anywhere(template: str) -> None:
    token = _ntfy_token()
    out = redact(template.format(token))
    assert token not in out
    assert REDACTED in out


def test_basic_authorization_is_redacted() -> None:
    pair = base64.b64encode(f"alerts:{secrets.token_urlsafe(16)}".encode()).decode()
    out = redact(f"Authorization: Basic {pair}")
    assert pair not in out
    assert REDACTED in out
