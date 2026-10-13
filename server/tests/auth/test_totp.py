# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The TOTP/HOTP algorithm (RFC 6238/4226 test vectors) and recovery codes (auth/totp.py)."""

import base64
from urllib.parse import parse_qs, urlsplit

import pytest

from ultimatetunes.auth import totp

# RFC 6238 Appendix B reference key (ASCII "12345678901234567890", 20 bytes, SHA-1).
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode("ascii")
# (unix time, expected 8-digit TOTP) from RFC 6238 Appendix B (SHA-1 rows).
RFC_VECTORS = [
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
]
# RFC 4226 Appendix D: HOTP values for counters 0..9 with the same key (6 digits).
RFC4226_HOTP = [
    "755224",
    "287082",
    "359152",
    "969429",
    "338314",
    "254676",
    "287922",
    "162583",
    "399871",
    "520489",
]


@pytest.mark.parametrize(("timestamp", "expected"), RFC_VECTORS)
def test_rfc6238_vectors(timestamp: int, expected: str) -> None:
    assert totp.code_at(RFC_SECRET, timestamp, digits=8) == expected


@pytest.mark.parametrize(("counter", "expected"), list(enumerate(RFC4226_HOTP)))
def test_rfc4226_hotp_vectors(counter: int, expected: str) -> None:
    assert totp.hotp(RFC_SECRET, counter) == expected


def test_hotp_refuses_negative_counter() -> None:
    with pytest.raises(ValueError, match="negative"):
        totp.hotp(RFC_SECRET, -1)


def test_generate_secret_is_valid_base32_of_the_right_size() -> None:
    secret = totp.generate_secret()
    assert secret == secret.upper()
    assert "=" not in secret
    decoded = base64.b32decode(secret + "=" * (-len(secret) % 8))
    assert len(decoded) == totp.SECRET_BYTES


def test_verify_accepts_the_current_code_and_returns_its_step() -> None:
    secret = totp.generate_secret()
    now = 1_700_000_000
    code = totp.code_at(secret, now)
    assert totp.verify(secret, code, now) == totp.step_at(now)


def test_verify_tolerates_one_step_of_drift_both_ways() -> None:
    secret = totp.generate_secret()
    now = 1_700_000_000
    assert totp.verify(secret, totp.code_at(secret, now - totp.PERIOD_S), now) is not None
    assert totp.verify(secret, totp.code_at(secret, now + totp.PERIOD_S), now) is not None


def test_verify_skips_negative_steps_near_the_epoch() -> None:
    # At timestamp 0 the window reaches step -1, which must be skipped, not computed.
    secret = totp.generate_secret()
    assert totp.verify(secret, totp.code_at(secret, 0), 0) == 0


def test_verify_rejects_a_code_two_steps_away() -> None:
    secret = totp.generate_secret()
    now = 1_700_000_000
    assert totp.verify(secret, totp.code_at(secret, now - 2 * totp.PERIOD_S), now) is None


def test_verify_rejects_a_zero_window_neighbour() -> None:
    secret = totp.generate_secret()
    now = 1_700_000_000
    assert totp.verify(secret, totp.code_at(secret, now - totp.PERIOD_S), now, window=0) is None
    assert totp.verify(secret, totp.code_at(secret, now), now, window=0) is not None


def test_verify_refuses_a_replayed_or_older_step() -> None:
    secret = totp.generate_secret()
    now = 1_700_000_000
    step = totp.step_at(now)
    code = totp.code_at(secret, now)
    # The same step is accepted once...
    assert totp.verify(secret, code, now, after_step=step - 1) == step
    # ...but refused once that step has already been spent.
    assert totp.verify(secret, code, now, after_step=step) is None


@pytest.mark.parametrize("bad", ["", "   ", "abcdef", "12345", "1234567", "१२३४५६", "12 34 56"])
def test_verify_fails_closed_on_malformed_input(bad: str) -> None:
    secret = totp.generate_secret()
    assert totp.verify(secret, bad, 1_700_000_000) is None


def test_otpauth_uri_carries_the_expected_parameters() -> None:
    secret = "JBSWY3DPEHPK3PXP"
    uri = totp.otpauth_uri(secret, "alice@example", "UltimateTunes")
    parts = urlsplit(uri)
    assert parts.scheme == "otpauth"
    assert parts.netloc == "totp"
    assert parts.path == "/UltimateTunes%3Aalice%40example"
    query = parse_qs(parts.query)
    assert query["secret"] == [secret]
    assert query["issuer"] == ["UltimateTunes"]
    assert query["digits"] == ["6"]
    assert query["period"] == ["30"]
    assert query["algorithm"] == ["SHA1"]


def test_recovery_codes_are_distinct_and_well_formed() -> None:
    codes = totp.generate_recovery_codes()
    assert len(codes) == totp.RECOVERY_CODE_COUNT
    assert len(set(codes)) == len(codes)
    for code in codes:
        groups = code.split("-")
        assert len(groups) == totp.RECOVERY_GROUPS
        assert all(len(g) == totp.RECOVERY_GROUP_LEN for g in groups)
        assert all(c in totp._RECOVERY_ALPHABET for g in groups for c in g)


def test_normalize_recovery_code_strips_formatting_and_ambiguity() -> None:
    assert totp.normalize_recovery_code("abcde-23456") == "ABCDE23456"
    assert totp.normalize_recovery_code("ABCDE 23456") == "ABCDE23456"
    # The ambiguous characters 0, 1, O, I, L are not in the alphabet, so they all drop out.
    assert totp.normalize_recovery_code("01OIL") == ""


def test_normalize_secret_uppercases_and_strips() -> None:
    assert totp.normalize_secret("jbsw y3dp===") == "JBSWY3DP"
