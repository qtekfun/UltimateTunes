# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""API key format (contracts/ids.md): `utk_` + 43 base64url characters (256 random bits).

Only the SHA-256 hex digest is stored, plus the first 12 characters as the display prefix. A
slow hash is not needed for a 256-bit random secret, and SHA-256 keeps every request cheap.
"""

import base64
import hashlib
import re
import secrets

_FORMAT = re.compile(r"utk_[A-Za-z0-9_-]{43}")
PREFIX_LENGTH = 12


def generate() -> str:
    raw = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    return "utk_" + raw


def is_well_formed(key: str) -> bool:
    return _FORMAT.fullmatch(key) is not None


def digest(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def prefix(key: str) -> str:
    return key[:PREFIX_LENGTH]


def decode_password(password: str) -> str | None:
    """The `p` parameter of OpenSubsonic: clear text, or `enc:` + hex of the UTF-8 bytes. None
    when the hex form is not valid."""
    if not password.startswith("enc:"):
        return password
    try:
        return bytes.fromhex(password[4:]).decode("utf-8")
    except ValueError:
        return None
