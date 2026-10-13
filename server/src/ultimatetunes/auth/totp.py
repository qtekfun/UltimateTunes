# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""TOTP (RFC 6238) and recovery codes for the optional second factor, standard library only.

No TOTP dependency is approved (CLAUDE.md, SPEC §6), so the algorithm is built here on `hmac`,
`hashlib`, `struct` and `base64`: HOTP (RFC 4226) over a time step counter, SHA-1 (what every
authenticator app defaults to), 6 digits, a 30 s period. `verify` checks a small window of
steps around the clock to tolerate drift and returns the matched step so the caller can refuse
a replay (a code accepted once is never accepted again, RFC 6238 §5.2).

Nothing here touches the clock or the database: the caller passes the current time (from the
injectable `Clock`) and keeps the last matched step. Secrets and recovery codes are values the
caller must never log; this module only computes and compares them in constant time.
"""

import base64
import hashlib
import hmac
import secrets
import struct
from urllib.parse import quote, urlencode

# Defaults every common authenticator app (Aegis, FreeOTP, Google Authenticator, ...) assumes.
DIGITS = 6
PERIOD_S = 30
ALGORITHM = "SHA1"
# 160 bits, the RFC 4226 recommended key size; 32 base32 characters.
SECRET_BYTES = 20
# Steps checked on each side of the current one: one 30 s step of tolerance for clock drift.
DEFAULT_WINDOW = 1

# Recovery codes: an unambiguous alphabet (no 0/O, 1/I/L), high entropy, grouped for reading.
_RECOVERY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
RECOVERY_GROUPS = 2
RECOVERY_GROUP_LEN = 5
RECOVERY_CODE_COUNT = 10


def generate_secret() -> str:
    """A fresh base32 TOTP secret (no padding, upper case), ready for an `otpauth://` URI."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode("ascii").rstrip("=")


def normalize_secret(secret: str) -> str:
    """Upper case, no spaces or padding: how a secret is compared and decoded."""
    return secret.replace(" ", "").upper().rstrip("=")


def _decode_secret(secret: str) -> bytes:
    cleaned = normalize_secret(secret)
    padding = "=" * (-len(cleaned) % 8)
    return base64.b32decode(cleaned + padding, casefold=True)


def hotp(secret: str, counter: int, *, digits: int = DIGITS) -> str:
    """The HOTP value (RFC 4226) of `secret` for `counter`, zero-padded to `digits`."""
    if counter < 0:
        raise ValueError("counter must not be negative")
    mac = hmac.new(_decode_secret(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    truncated = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % (10**digits)).zfill(digits)


def step_at(timestamp: int, *, period_s: int = PERIOD_S) -> int:
    """The TOTP time step counter for a unix timestamp (RFC 6238)."""
    return timestamp // period_s


def code_at(secret: str, timestamp: int, *, digits: int = DIGITS, period_s: int = PERIOD_S) -> str:
    """The TOTP code of `secret` at a unix `timestamp` (what the authenticator app shows)."""
    return hotp(secret, step_at(timestamp, period_s=period_s), digits=digits)


def _looks_like_code(code: str, digits: int) -> bool:
    return len(code) == digits and code.isdigit() and code.isascii()


def verify(  # noqa: PLR0913 - the RFC 6238 parameters (digits, period, window, replay guard)
    secret: str,
    code: str,
    timestamp: int,
    *,
    digits: int = DIGITS,
    period_s: int = PERIOD_S,
    window: int = DEFAULT_WINDOW,
    after_step: int | None = None,
) -> int | None:
    """Returns the time step a `code` matches within `window` steps of `timestamp`, or None.

    Every candidate is compared in constant time; a non-numeric or wrong-length code fails
    closed without touching the secret. `after_step` refuses a code from a step already used
    (replay protection): only steps strictly greater than it are accepted.
    """
    submitted = code.strip()
    if not _looks_like_code(submitted, digits):
        return None
    current = step_at(timestamp, period_s=period_s)
    matched: int | None = None
    # Walk every candidate (no early return) so the time taken does not reveal which step hit.
    for step in range(current - window, current + window + 1):
        if step < 0:
            continue
        expected = hotp(secret, step, digits=digits)
        if hmac.compare_digest(expected, submitted) and (after_step is None or step > after_step):
            matched = step
    return matched


def otpauth_uri(
    secret: str,
    account_name: str,
    issuer: str,
    *,
    digits: int = DIGITS,
    period_s: int = PERIOD_S,
) -> str:
    """The `otpauth://totp/...` URI an authenticator app reads from the enrollment QR code."""
    label = quote(f"{issuer}:{account_name}", safe="")
    params = urlencode(
        {
            "secret": normalize_secret(secret),
            "issuer": issuer,
            "algorithm": ALGORITHM,
            "digits": digits,
            "period": period_s,
        }
    )
    return f"otpauth://totp/{label}?{params}"


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    """`count` one-time recovery codes, formatted `XXXXX-XXXXX` from an unambiguous alphabet."""
    return [
        "-".join(
            "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(RECOVERY_GROUP_LEN))
            for _ in range(RECOVERY_GROUPS)
        )
        for _ in range(count)
    ]


def normalize_recovery_code(code: str) -> str:
    """How a recovery code is compared: upper case, spaces and hyphens removed."""
    return "".join(c for c in code.upper() if c in _RECOVERY_ALPHABET)
