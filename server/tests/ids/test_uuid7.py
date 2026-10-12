# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""UUIDv7 generation (RFC 9562) from the injectable clock."""

import re
import uuid
from datetime import UTC, datetime

import pytest

from ultimatetunes.core.clock import FakeClock
from ultimatetunes.ids import new_id

LOWER_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def test_layout_version_variant_and_time() -> None:
    clock = FakeClock()
    value = new_id(clock)
    assert LOWER_UUID.match(value)
    parsed = uuid.UUID(value)
    assert parsed.version == 7
    assert parsed.variant == uuid.RFC_4122
    assert parsed.int >> 80 == int(clock.now().timestamp() * 1000)


def test_ids_follow_time_and_are_unique() -> None:
    clock = FakeClock()
    first = new_id(clock)
    clock.advance(0.001)
    second = new_id(clock)
    assert first < second
    assert len({new_id(clock) for _ in range(1000)}) == 1000


def test_times_outside_the_range_are_refused() -> None:
    clock = FakeClock(datetime(1960, 1, 1, tzinfo=UTC))
    with pytest.raises(ValueError, match="range"):
        new_id(clock)
