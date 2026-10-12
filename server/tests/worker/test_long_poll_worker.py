# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The worker side of long-poll claims (issue #55): what it does after an empty claim, and
that a stop abandons a claim the api is holding instead of waiting for it."""

from typing import Any

import anyio
import pytest

from ultimatetunes.core.storage import LocalLibraryStore, LocalStagingStore
from ultimatetunes.errors import TunesError
from ultimatetunes.settings import Settings
from ultimatetunes.worker.archiver import PendingArchiver
from ultimatetunes.worker.client import ApiUnavailableError, NoJob
from ultimatetunes.worker.fake import FakeDownloader
from ultimatetunes.worker.loop import Worker
from ultimatetunes.worker.settings import WorkerSettings

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class Answers:
    """Answers each claim with the next item (raised when it is an exception)."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.claims = 0
        self.held = anyio.Event()

    async def claim(self, worker_id: str, lease_s: int) -> Any:
        self.claims += 1
        answer = self.answers.pop(0)
        if answer == "hold":
            self.held.set()
            await anyio.sleep_forever()
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def report_status(self, worker_id: str, **fields: Any) -> list[str]:
        return []


def worker(settings: Settings, api: Answers) -> Worker:
    staging = LocalStagingStore(settings.staging_dir)
    return Worker(
        api=api,  # type: ignore[arg-type]
        downloader=FakeDownloader(staging),
        archiver=PendingArchiver(),
        staging=staging,
        library=LocalLibraryStore(settings.music_dir),
        settings=WorkerSettings(poll_interval_s=2.0),
        worker_id="w1",
    )


@pytest.mark.parametrize("stop", [None, anyio.Event])
async def test_after_an_empty_claim_the_worker_waits_what_the_api_said(
    settings: Settings, stop: Any
) -> None:
    api = Answers(NoJob(0.0), NoJob(3.0), NoJob(None))
    w = worker(settings, api)
    event = stop() if stop else None
    # 0 after a long poll: at once; the api's delay; the poll interval when it did not say.
    assert [await w.run_once(event) for _ in range(3)] == [0.0, 3.0, 2.0]


@pytest.mark.parametrize("error", [ApiUnavailableError("down"), TunesError("refused")])
async def test_a_failed_claim_waits_the_poll_interval(settings: Settings, error: Exception) -> None:
    api = Answers(error)
    assert await worker(settings, api).run_once(anyio.Event()) == 2.0


async def test_a_stop_abandons_a_held_claim(settings: Settings) -> None:
    api = Answers("hold")
    w = worker(settings, api)
    stop = anyio.Event()
    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:

            async def stop_when_held() -> None:
                await api.held.wait()
                stop.set()

            tg.start_soon(stop_when_held)
            assert await w.run_once(stop) == 0.0
    assert api.claims == 1


async def test_run_ends_promptly_when_stopped_during_a_held_claim(settings: Settings) -> None:
    api = Answers("hold")
    w = worker(settings, api)
    stop = anyio.Event()
    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            tg.start_soon(w.run, stop)
            await api.held.wait()
            stop.set()
    assert api.claims == 1
