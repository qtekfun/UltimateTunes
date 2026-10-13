# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Authenticated encryption of the TOTP shared secret at rest (SECURITY.md, docs/2fa.md).

The TOTP secret must be reversible (the server recomputes codes from it), so it cannot be a
hash. It is sealed with `cryptography.fernet.Fernet` (AES-128-CBC + HMAC-SHA256) under a key the
operator provides out of band (`UT_TOTP_ENCRYPTION_KEY`, a urlsafe-base64 32-byte Fernet key,
from an env var or a Docker secret), so a stolen database is not enough to read the secrets.

Without the key the box is **unavailable**: encrypt and decrypt raise `FeatureDisabled`, so
2FA enrollment and verification fail closed with a clear operator error instead of ever falling
back to plaintext. The key never reaches a log (it lives in a `SecretStr` and is never logged).
"""

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from ultimatetunes.errors import FeatureDisabled

__all__ = ["InvalidToken", "SecretBox"]

NO_KEY_MESSAGE = "Two-factor authentication needs UT_TOTP_ENCRYPTION_KEY to be set"


class SecretBox:
    """Seals and opens short secrets with Fernet, or fails closed when no key is configured."""

    def __init__(self, key: SecretStr | None) -> None:
        self._fernet = None if key is None else Fernet(key.get_secret_value().encode("ascii"))

    @property
    def available(self) -> bool:
        return self._fernet is not None

    def encrypt(self, plaintext: str) -> str:
        """The sealed token (urlsafe-base64 text) of `plaintext`. Raises if no key is set."""
        return self._cipher().encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        """The plaintext of a sealed `token`. Raises `InvalidToken` on a wrong key or tamper,
        `FeatureDisabled` when no key is set."""
        return self._cipher().decrypt(token.encode("ascii")).decode("utf-8")

    def _cipher(self) -> Fernet:
        if self._fernet is None:
            raise FeatureDisabled(NO_KEY_MESSAGE)
        return self._fernet
