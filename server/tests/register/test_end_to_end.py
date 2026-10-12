# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Worker → api, end to end in process: the fake downloader, the real tagging archiver (real
ffmpeg, no lookups), the real internal API. download → tag → register → move → complete →
track ready with its file in the library; and a retry after the file was moved but the
attempt died before `complete` adopts it (no orphan, no duplicate)."""

from pathlib import Path

import anyio
import pytest

from tests.jobs.test_queue import add_track
from tests.register.test_register import TOKEN, VIDEO, Api
from tests.tagging.conftest import needs_ffmpeg, real_settings
from ultimatetunes.errors import WorkerErrorCode
from ultimatetunes.tagging.archiver import TaggingArchiver
from ultimatetunes.worker.archiver import Archived, ArchiveRequest
from ultimatetunes.worker.client import HttpWorkerApi
from ultimatetunes.worker.downloader import DownloadError
from ultimatetunes.worker.fake import FakeDownloader
from ultimatetunes.worker.loop import Worker
from ultimatetunes.worker.settings import WorkerSettings

pytestmark = [pytest.mark.anyio, needs_ffmpeg]
FILE = "The Paper Lanterns/Glass Orchard/Glass Orchard.opus"
TRACK = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c001"


async def no_sleep(_seconds: float) -> None:
    await anyio.lowlevel.checkpoint()


def tagging() -> TaggingArchiver:
    return TaggingArchiver(real_settings(), lookups=False)


class DiesAfterTheMove:
    """The first attempt archives (file moved into /music) and then dies before `complete`."""

    def __init__(self) -> None:
        self.inner = tagging()
        self.calls = 0

    async def archive(self, request: ArchiveRequest) -> Archived:
        self.calls += 1
        archived = await self.inner.archive(request)
        if self.calls == 1:
            raise DownloadError(WorkerErrorCode.STORAGE_ERROR, "died before complete")
        return archived


def worker(api: Api, archiver: object) -> Worker:
    return Worker(
        api=HttpWorkerApi(api.client, TOKEN, retries=0),
        downloader=FakeDownloader(api.services.staging, chunks=2, sleep=no_sleep),
        archiver=archiver,  # type: ignore[arg-type]
        staging=api.services.staging,
        library=api.services.library,
        settings=WorkerSettings(lease_s=60, poll_interval_s=0.01),
        worker_id="w1",
        clock=api.clock,
        sleep=no_sleep,
    )


def enqueue(api: Api) -> str:
    add_track(api.db, api.clock, TRACK, VIDEO)
    return api.services.jobs.enqueue(track_id=TRACK, video_id=VIDEO, priority=100).id


async def test_download_tag_register_move_complete(api: Api) -> None:
    job_id = enqueue(api)
    assert await worker(api, tagging()).run_once() == 0.0
    job = api.services.jobs.get(job_id)
    assert job is not None
    assert job.state == "ready"
    track = api.row("SELECT * FROM tracks WHERE id = ?", TRACK)
    assert (track["status"], track["path"], track["format"]) == ("ready", FILE, "opus")
    assert track["needs_review"] == 1  # no lookups in the test stack
    assert api.services.library.size(FILE) == track["size_bytes"]
    assert track["album_id"] is not None
    assert track["artist_id"] is not None
    with api.services.library.open_read(FILE) as reader:
        archived = reader.read()
    assert archived.startswith(b"OggS")
    # Streamable through the OpenSubsonic `stream` of T05.
    played = await api.client.get("/rest/stream", params={"apiKey": "utk_ana", "id": TRACK})
    assert played.status_code == 200, played.text
    assert played.content == archived
    assert played.headers["content-type"].startswith("audio/ogg")


async def test_a_retry_adopts_the_file_moved_before_a_crash(api: Api) -> None:
    job_id = enqueue(api)
    archiver = DiesAfterTheMove()
    first = await worker(api, archiver).run_once()
    assert first == 0.0
    job = api.services.jobs.get(job_id)
    assert job is not None
    assert (job.state, job.library_path) == ("queued", None)
    assert api.services.library.exists(FILE)  # moved, no owner yet
    api.clock.advance(3600)
    assert await worker(api, archiver).run_once() == 0.0
    job = api.services.jobs.get(job_id)
    assert job is not None
    assert job.state == "ready"
    assert api.row("SELECT status, path FROM tracks WHERE id = ?", TRACK)[:] == ("ready", FILE)
    album_dir = Path(api.services.library.local_path(FILE)).parent
    assert sorted(p.name for p in album_dir.iterdir()) == ["Glass Orchard.opus"]
