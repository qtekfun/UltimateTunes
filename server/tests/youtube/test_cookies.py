# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The encrypted YouTube cookies store (D14): validation, round-trip, status without
decrypting, and fail-closed when no key is configured. No network, invented cookies only."""

import json
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from ultimatetunes.core.clock import FakeClock
from ultimatetunes.db import Database
from ultimatetunes.errors import FeatureDisabled, InvalidParameter
from ultimatetunes.youtube.cookies import (
    SETTING_KEY,
    YouTubeCookieStore,
    validate_netscape,
)
from ultimatetunes.youtube.settings import YouTubeSettings

COOKIE_VALUE = "EXAMPLE-invented-cookie-NOLEAK"
COOKIES = (
    "# Netscape HTTP Cookie File\n"
    f".youtube.com\tTRUE\t/\tTRUE\t1999999999\tSID\t{COOKIE_VALUE}\n"
    f"#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t1999999999\tHSID\t{COOKIE_VALUE}2\n"
)


def _store(db: Database, clock: FakeClock, *, key: str | None) -> YouTubeCookieStore:
    secret = SecretStr(key) if key is not None else None
    return YouTubeCookieStore(db, clock, YouTubeSettings(ytdlp_cookies_key=secret))


def _key() -> str:
    return Fernet.generate_key().decode("ascii")


def test_validate_netscape_counts_cookies_and_youtube_domain() -> None:
    assert validate_netscape(COOKIES) == (2, True)
    other = "# Netscape HTTP Cookie File\n.example.com\tTRUE\t/\tFALSE\t0\ta\tb\n"
    assert validate_netscape(other) == (1, False)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not cookies at all",
        '{"json": true}',
        "# Netscape HTTP Cookie File\n",  # header only, no cookie lines
        "# Netscape HTTP Cookie File\n.youtube.com only three fields\n",
        ".youtube.com\tTRUE\t/\tTRUE\t1999999999\tSID\tv\n",  # no header
    ],
)
def test_validate_netscape_rejects_bad_input(text: str) -> None:
    with pytest.raises(InvalidParameter):
        validate_netscape(text)


def test_set_stores_ciphertext_and_round_trips(
    settings: object, db: Database, clock: FakeClock
) -> None:
    store = _store(db, clock, key=_key())
    status = store.set(COOKIES)
    assert (status.configured, status.cookie_count, status.has_youtube_domain) == (True, 2, True)
    # The stored row is ciphertext JSON: the cookie value never appears in clear.
    with db.read() as conn:
        raw = conn.execute("SELECT value FROM settings WHERE key = ?", (SETTING_KEY,)).fetchone()
    assert raw is not None
    stored = str(raw["value"])
    assert COOKIE_VALUE not in stored
    assert "sealed" in json.loads(stored)
    # It decrypts back to exactly the uploaded text.
    assert store.current() == COOKIES


def test_status_does_not_decrypt_and_leaks_no_value(
    settings: object, db: Database, clock: FakeClock
) -> None:
    store = _store(db, clock, key=_key())
    store.set(COOKIES)
    status = store.status()
    assert status.configured
    assert status.cookie_count == 2
    assert COOKIE_VALUE not in repr(status)


def test_clear_removes_the_cookies(settings: object, db: Database, clock: FakeClock) -> None:
    store = _store(db, clock, key=_key())
    store.set(COOKIES)
    store.clear()
    assert store.status() == store.status().__class__(False)
    assert store.current() is None


def test_fails_closed_without_a_key(settings: object, db: Database, clock: FakeClock) -> None:
    store = _store(db, clock, key=None)
    assert not store.available
    with pytest.raises(FeatureDisabled):
        store.set(COOKIES)
    # Nothing was written, and current() never returns a plaintext fallback.
    assert store.current() is None


def test_a_wrong_key_cannot_read_an_existing_blob(
    settings: object, db: Database, clock: FakeClock
) -> None:
    _store(db, clock, key=_key()).set(COOKIES)
    from cryptography.fernet import InvalidToken  # noqa: PLC0415

    other = _store(db, clock, key=_key())
    with pytest.raises(InvalidToken):
        other.current()


def test_the_key_must_be_a_valid_fernet_key(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Fernet key"):
        YouTubeSettings(ytdlp_cookies_key=SecretStr("not-a-fernet-key"))
