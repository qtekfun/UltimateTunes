# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""UUIDv7 (RFC 9562) from the injectable clock, until Python 3.14 brings `uuid.uuid7()`.

Layout: 48-bit Unix time in milliseconds, version `7`, 12 random bits, variant `10`, 62 random
bits. Ids from the same millisecond are not ordered among themselves; that is fine for B-tree
locality and for "roughly by creation time" ordering (contracts/ids.md).
"""

import secrets
import uuid

from ultimatetunes.core.clock import Clock

_MAX_MS = (1 << 48) - 1


def new_id(clock: Clock) -> str:
    """A new lowercase hyphenated UUIDv7, e.g. `0199d6a2-4c1e-7b3a-9f10-2a6c8e01b001`."""
    ms = int(clock.now().timestamp() * 1000)
    if not 0 <= ms <= _MAX_MS:
        raise ValueError("time outside the UUIDv7 range")
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    value = (ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return str(uuid.UUID(int=value))
