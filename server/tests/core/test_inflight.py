# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""InFlight: single flight per key and listener counting."""

import anyio
import pytest

from ultimatetunes.core.inflight import MemoryInFlight

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_concurrent_callers_share_one_execution() -> None:
    inflight = MemoryInFlight()
    calls = 0
    gate = anyio.Event()

    async def work() -> str:
        nonlocal calls
        calls += 1
        await gate.wait()
        return "result"

    results: list[str] = []

    async def caller() -> None:
        results.append(await inflight.run("search:lanterns", work))

    async with anyio.create_task_group() as tg:
        for _ in range(3):
            tg.start_soon(caller)
        await anyio.wait_all_tasks_blocked()
        assert inflight.running("search:lanterns")
        gate.set()
    assert results == ["result"] * 3
    assert calls == 1
    assert not inflight.running("search:lanterns")


async def test_errors_are_shared_and_the_key_is_freed() -> None:
    inflight = MemoryInFlight()

    async def boom() -> None:
        raise LookupError("nope")

    with pytest.raises(LookupError):
        await inflight.run("k", boom)

    async def ok() -> int:
        return 7

    assert await inflight.run("k", ok) == 7


async def test_listeners_are_counted() -> None:
    inflight = MemoryInFlight()
    assert inflight.listeners("yt:Qx7Lm2pZ0aB") == 0
    async with inflight.listen("yt:Qx7Lm2pZ0aB") as first:
        assert first == 1
        async with inflight.listen("yt:Qx7Lm2pZ0aB") as second:
            assert second == 2
        assert inflight.listeners("yt:Qx7Lm2pZ0aB") == 1
    assert inflight.listeners("yt:Qx7Lm2pZ0aB") == 0
