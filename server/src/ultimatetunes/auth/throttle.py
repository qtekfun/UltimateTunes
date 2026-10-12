# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Brute-force brakes of `AuthService` besides the per-IP and per-user lockout (SECURITY.md).

- `client_key`: the address a failure is counted against. IPv4 as is; **IPv6 by its /64**, the
  block one subscriber usually gets, so rotating addresses inside it never resets the counter.
- `Argon2Slots`: at most `UT_AUTH_ARGON2_CONCURRENCY` password verifications run at once in
  this process (each one takes ~19 MiB and a CPU core). A check that finds no free slot within
  `UT_AUTH_ARGON2_WAIT_S` is refused with `RateLimited` before Argon2 runs. One instance per
  process (`shared_slots`), whatever the number of `AuthService` objects.
- The global failure budget (`AuthService`): more than `UT_AUTH_MAX_FAILURES_GLOBAL_PER_MIN`
  failed attempts per minute from outside the admin's networks lock password checks from
  outside and every unknown key for `UT_AUTH_GLOBAL_LOCKOUT_S` (a valid API key is never
  refused for it, and the admin panel, behind its allowlist, is exempt).
"""

import ipaddress
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from ultimatetunes.auth.settings import AuthSettings
from ultimatetunes.core.netaddr import parse_ip
from ultimatetunes.errors import RateLimited

IPV6_GROUP = 64
UNKNOWN = "unknown"


def client_key(client_ip: str | None) -> str:
    """The rate-limit key of a client address (module doc)."""
    address = parse_ip(client_ip)
    if address is None:
        return client_ip or UNKNOWN
    if address.version == 6:  # noqa: PLR2004 - the IP version
        return str(ipaddress.ip_network(f"{address}/{IPV6_GROUP}", strict=False))
    return str(address)


class Argon2Slots:
    def __init__(self, slots: int, wait_s: float) -> None:
        if slots < 1 or wait_s < 0:
            raise ValueError("slots must be positive and wait_s not negative")
        self._slots = threading.BoundedSemaphore(slots)
        self._wait_s = wait_s

    @contextmanager
    def slot(self) -> Iterator[None]:
        """Holds one slot while the block runs, or raises `RateLimited` (module doc)."""
        if not self._slots.acquire(timeout=self._wait_s):
            raise RateLimited(1, "Too many sign-ins at once, try again in a moment")
        try:
            yield
        finally:
            self._slots.release()


@lru_cache(maxsize=1)
def shared_slots() -> Argon2Slots:
    settings = AuthSettings()
    return Argon2Slots(settings.auth_argon2_concurrency, settings.auth_argon2_wait_s)
