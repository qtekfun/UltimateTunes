# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Injectable time (CLAUDE.md: never `time.time()`/`datetime.now()` in testable logic).

Timestamps stored in the database are TEXT in the fixed-width UTC form
`YYYY-MM-DDTHH:MM:SS.mmmZ` (contracts/db/README.md), so text order is time order.
"""

import time
from datetime import UTC, datetime, timedelta
from typing import Protocol, override


class Clock(Protocol):
    def now(self) -> datetime:
        """Current time, timezone-aware UTC."""
        ...

    def monotonic(self) -> float:
        """Seconds from an arbitrary origin that never goes backwards (durations only)."""
        ...


class SystemClock:
    """The real clock."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()


class FakeClock:
    """A clock that only moves when told to. Starts at 2026-10-12T08:00:00.000Z by default."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 10, 12, 8, 0, tzinfo=UTC)
        if self._now.tzinfo is None:
            raise ValueError("FakeClock needs a timezone-aware start")
        self._mono = 1000.0

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("time never goes backwards")
        self._now += timedelta(seconds=seconds)
        self._mono += seconds

    @override
    def __repr__(self) -> str:
        return f"FakeClock({format_ts(self._now)})"


def format_ts(moment: datetime) -> str:
    """`2026-10-12T08:15:30.123Z`: UTC, millisecond precision, fixed width."""
    if moment.tzinfo is None:
        raise ValueError("naive datetimes are not allowed")
    utc = moment.astimezone(UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


def parse_ts(text: str) -> datetime:
    """Inverse of `format_ts`."""
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
