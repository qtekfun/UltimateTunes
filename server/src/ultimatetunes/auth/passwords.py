# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Account passwords: Argon2id (CLAUDE.md, Security), and the password policy.

Parameters follow the OWASP minimum for Argon2id (19 MiB, 2 iterations, 1 lane) instead of
argon2-cffi's 64 MiB default, to stay inside the server's RAM budget when several logins run at
once (SPEC §6); `needs_rehash` upgrades stored hashes when the parameters change. Passwords are
only used for the admin panel and to create API keys, never on `/rest` (SPEC RF-02).
"""

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

from ultimatetunes.errors import InvalidParameter

MIN_LENGTH = 12
MAX_LENGTH = 1024


def check_policy(password: str) -> None:
    """New passwords: 12 to 1024 characters (contracts/openapi/ut-v1.yaml caps the length)."""
    if not MIN_LENGTH <= len(password) <= MAX_LENGTH:
        raise InvalidParameter(f"The password must have {MIN_LENGTH} to {MAX_LENGTH} characters")


def default_hasher() -> PasswordHasher:
    return PasswordHasher(time_cost=2, memory_cost=19 * 1024, parallelism=1, type=Type.ID)


class Passwords:
    def __init__(self, hasher: PasswordHasher | None = None) -> None:
        self._hasher = hasher or default_hasher()
        self._dummy: str | None = None

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, stored_hash: str, password: str) -> bool:
        """True when `password` matches; a corrupt or foreign hash never matches."""
        try:
            return self._hasher.verify(stored_hash, password)
        except (VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, stored_hash: str) -> bool:
        return self._hasher.check_needs_rehash(stored_hash)

    def burn(self, password: str) -> None:
        """Spends the time of one verification, so an unknown username answers as slowly as a
        wrong password (no user enumeration by timing)."""
        if self._dummy is None:
            self._dummy = self._hasher.hash("not a real password, only for timing")
        self.verify(self._dummy, password)
