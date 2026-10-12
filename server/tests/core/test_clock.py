# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Injectable clock and the database timestamp format."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from ultimatetunes.core.clock import FakeClock, SystemClock, format_ts, parse_ts


def test_format_is_fixed_width_utc_millis() -> None:
    moment = datetime(2026, 10, 12, 10, 15, 30, 123456, tzinfo=timezone(timedelta(hours=2)))
    assert format_ts(moment) == "2026-10-12T08:15:30.123Z"
    assert parse_ts("2026-10-12T08:15:30.123Z") == datetime(
        2026, 10, 12, 8, 15, 30, 123000, tzinfo=UTC
    )


def test_naive_datetimes_are_refused() -> None:
    with pytest.raises(ValueError, match="naive"):
        format_ts(datetime(2026, 1, 1))  # noqa: DTZ001 - the point of the test
    with pytest.raises(ValueError, match="timezone-aware"):
        FakeClock(datetime(2026, 1, 1))  # noqa: DTZ001


def test_fake_clock_moves_only_forward_when_told() -> None:
    clock = FakeClock()
    start, mono = clock.now(), clock.monotonic()
    clock.advance(1.5)
    assert clock.now() - start == timedelta(seconds=1.5)
    assert clock.monotonic() - mono == 1.5
    assert "2026-10-12T08:00:01.500Z" in repr(clock)
    with pytest.raises(ValueError, match="backwards"):
        clock.advance(-1)


def test_system_clock_is_aware_and_monotonic() -> None:
    clock = SystemClock()
    assert clock.now().tzinfo is UTC
    assert clock.monotonic() <= clock.monotonic()
