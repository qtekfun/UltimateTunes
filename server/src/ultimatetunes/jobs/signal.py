# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`JobSignal` and the long-poll claim (issue #55, contracts/openapi/internal-worker.yaml).

An idle worker's claim may wait (`waitSeconds`): the api holds it and claims again as soon as
a job may be claimable, instead of answering 204 at once and letting the worker sleep up to
`Retry-After` seconds before a new job even starts downloading.

`JobSignal` is in-process: `JobQueue.enqueue_in` fires it whenever a job becomes `queued`, from
any thread. It may fire before the enqueuing transaction commits; the woken claim still sees
the job, because its own write transaction waits for the single writer (`Database`). Jobs that
become claimable without passing through this process (another api replica later, a retry
whose backoff ends, an expired lease) are found by re-claiming at least every `poll_s` while
the request waits, so the signal only shortens the wait and is never needed for correctness.
"""

import asyncio
import threading
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager, suppress


class JobSignal:
    """Wakes the claims waiting in this process. `notify` is safe from any thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._waiters: set[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = set()

    @contextmanager
    def listen(self) -> Iterator[asyncio.Event]:
        """An event set by every `notify` while the block runs. Listen before checking for a
        job, so a job queued between the check and the wait is not missed."""
        waiter = (asyncio.get_running_loop(), asyncio.Event())
        with self._lock:
            self._waiters.add(waiter)
        try:
            yield waiter[1]
        finally:
            with self._lock:
                self._waiters.discard(waiter)

    def notify(self) -> None:
        with self._lock:
            waiters = list(self._waiters)
        for loop, event in waiters:
            with suppress(RuntimeError):  # that loop is already closed: nobody waits there
                loop.call_soon_threadsafe(event.set)


async def claim_waiting[T](
    attempt: Callable[[], Awaitable[T | None]],
    signal: JobSignal,
    *,
    wait_s: float,
    poll_s: float,
) -> T | None:
    """`attempt()` at once and, while it finds nothing, again whenever `signal` fires and at
    least every `poll_s`, until `wait_s` have passed (event loop time). None when nothing came."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_s
    while True:
        with signal.listen() as woken:
            found = await attempt()
            remaining = deadline - loop.time()
            if found is not None or remaining <= 0:
                return found
            with suppress(TimeoutError):
                async with asyncio.timeout(min(poll_s, remaining)):
                    await woken.wait()
