# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""End to end: a client streams a `yt:` id while the real worker loop downloads it with the
fake downloader (writing slowly) over the internal worker API of the same live api."""

import anyio
import httpx
import pytest

from tests.streaming.harness import TOKEN, VIDEO, Live, serve, until
from tests.streaming.test_stream import start
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.errors import WorkerErrorCode
from ultimatetunes.settings import Settings
from ultimatetunes.worker.archiver import Archived, ArchiveRequest
from ultimatetunes.worker.client import HttpWorkerApi
from ultimatetunes.worker.fake import FakeDownloader, silence_opus
from ultimatetunes.worker.loop import Worker
from ultimatetunes.worker.settings import WorkerSettings

pytestmark = pytest.mark.anyio
LIBRARY_PATH = "The Paper Lanterns/Glass Orchard.opus"


class Registering:
    """Stands in for T09: registers the download and moves it into the library."""

    def __init__(self, live: Live) -> None:
        self.live = live

    async def archive(self, request: ArchiveRequest) -> Archived:
        size = request.staging.size(request.download.final_path)
        with self.live.services.db.transaction() as conn:
            conn.execute(
                "UPDATE tracks SET size_bytes = ?, format = 'opus' WHERE id = ?",
                (size, request.job.track_id),
            )
            conn.execute(
                "UPDATE jobs SET library_path = ? WHERE id = ?",
                (LIBRARY_PATH, request.job.job_id),
            )
        request.library.import_file(request.staging, request.download.final_path, LIBRARY_PATH)
        return Archived(request.job.track_id, LIBRARY_PATH)


def worker(live: Live, client: httpx.AsyncClient, downloader: FakeDownloader) -> Worker:
    return Worker(
        api=HttpWorkerApi(client, TOKEN, retries=0),
        downloader=downloader,
        archiver=Registering(live),
        staging=live.services.staging,
        library=live.services.library,
        settings=WorkerSettings(lease_s=15, poll_interval_s=0.01, blocked_pause_s=60.0),
        worker_id="w1",
        clock=live.clock,
    )


async def test_first_play_while_the_worker_downloads_then_from_the_library(
    stream_settings: Settings, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A slow fallback poll: the worker's reports wake the listeners (middleware), not the poll.
    monkeypatch.setenv("UT_STREAM_POLL_INTERVAL_S", "0.5")
    async with (
        serve(stream_settings, clock) as live,
        httpx.AsyncClient(base_url=live.url) as internal,
    ):
        downloader = FakeDownloader(live.services.staging, chunks=8, delay_s=0.05)
        async with anyio.create_task_group() as group:
            ana = start(live, group)
            bob = start(live, group, key="utk_bob")
            await until(lambda: live.job() is not None)
            with anyio.fail_after(10):
                await worker(live, internal, downloader).run_once()
            await ana.done.wait()
            await bob.done.wait()
        assert downloader.downloads == [VIDEO]
        assert ana.error is None
        assert ana.status == 200
        assert ana.headers["content-type"] == "audio/ogg"
        assert ana.headers["content-length"] == str(len(silence_opus()))
        assert bytes(ana.body) == bytes(bob.body) == silence_opus()
        job = live.job()
        assert job is not None
        assert job.state == "ready"
        # The staging directory goes once the last listener closed and the job is done.
        await until(lambda: not (stream_settings.staging_dir / job.id).exists())
        # Later plays of the yt: id come from the archived file (its alias).
        again = await live.client.get("/rest/stream", params=live.params(live.song()))
        assert again.status_code == 200
        assert again.content == silence_opus()
        assert "cache-control" not in again.headers


async def test_a_download_failing_mid_stream_cuts_it(live: Live) -> None:
    async with httpx.AsyncClient(base_url=live.url) as internal:
        downloader = FakeDownloader(
            live.services.staging,
            chunks=8,
            delay_s=0.05,
            fail_after_bytes=300,
            fail_code=WorkerErrorCode.VIDEO_UNAVAILABLE,
        )
        async with anyio.create_task_group() as group:
            listening = start(live, group)
            await until(lambda: live.job() is not None)
            with anyio.fail_after(10):
                await worker(live, internal, downloader).run_once()
            await listening.done.wait()
        assert isinstance(listening.error, httpx.RemoteProtocolError)
        job = live.job()
        assert job is not None
        assert job.state == "failed"
        retry = await live.client.get("/rest/stream", params=live.params(live.song()))
        assert retry.status_code == 404
        # Nobody streams any more and the job failed: its attempt directory is gone.
        await until(lambda: not (live.services.settings.staging_dir / job.id / "1").exists())
