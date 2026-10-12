# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`InFlight`: work and listeners currently in progress, per key.

- `run(key, work)`: single flight. Concurrent callers with the same key share one execution and
  its result (or exception). The work runs as its own task, so a caller that goes away does not
  cancel it for the others. Used to deduplicate catalog calls (T06) and downloads (T16).
- `listen(key)`: registers a listener (e.g. a client tailing a growing staging file, T16) for the
  duration of a `with` block; `listeners(key)` tells whether the staging file can be cleaned.

`MemoryInFlight` is the v1 implementation (one api process). Several replicas (phase 5) need a
shared one (Redis) behind the same protocol.
"""

import asyncio
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Protocol, cast


class InFlight(Protocol):
    async def run[T](self, key: str, work: Callable[[], Awaitable[T]]) -> T: ...

    def running(self, key: str) -> bool: ...

    def listen(self, key: str) -> AbstractAsyncContextManager[int]:
        """Counts a listener while the block runs; yields the count including this one."""
        ...

    def listeners(self, key: str) -> int: ...


class MemoryInFlight:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._listeners: Counter[str] = Counter()

    async def run[T](self, key: str, work: Callable[[], Awaitable[T]]) -> T:
        task = self._tasks.get(key)
        if task is None:

            async def call() -> T:
                return await work()

            task = asyncio.ensure_future(call())
            self._tasks[key] = task
            task.add_done_callback(lambda _done: self._tasks.pop(key, None))
        return cast("T", await asyncio.shield(task))

    def running(self, key: str) -> bool:
        return key in self._tasks

    @asynccontextmanager
    async def _listen(self, key: str) -> AsyncIterator[int]:
        self._listeners[key] += 1
        try:
            yield self._listeners[key]
        finally:
            self._listeners[key] -= 1
            if self._listeners[key] <= 0:
                del self._listeners[key]

    def listen(self, key: str) -> AbstractAsyncContextManager[int]:
        return self._listen(key)

    def listeners(self, key: str) -> int:
        return self._listeners.get(key, 0)
