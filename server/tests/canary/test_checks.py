# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The canary checks with the fake catalog and the fake downloader: passing runs, every kind of
failure reported (never raised), and the download always deleted, never archived."""

import json
from dataclasses import replace
from pathlib import Path

import anyio
import pytest

from tests.canary.conftest import FAKE_TARGETS
from ultimatetunes.canary.checks import (
    MAX_MESSAGE,
    STAGING_ROOT,
    CatalogCanary,
    Check,
    DownloadCanary,
    Report,
    run_check,
    targets,
)
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.core.storage import LocalStagingStore
from ultimatetunes.errors import WorkerErrorCode
from ultimatetunes.search.catalog import (
    CatalogAlbumRef,
    CatalogNotFound,
    CatalogParseError,
    CatalogPlaylist,
    CatalogThrottled,
    CatalogTrack,
)
from ultimatetunes.search.fake import FakeMusicCatalog
from ultimatetunes.settings import Settings
from ultimatetunes.worker.downloader import DownloadResult, ProgressCallback
from ultimatetunes.worker.fake import FakeDownloader

pytestmark = pytest.mark.anyio


def catalog_canary(catalog: object, clock: FakeClock, timeout_s: float = 5.0) -> CatalogCanary:
    return CatalogCanary(catalog, FAKE_TARGETS, clock, timeout_s)  # type: ignore[arg-type]


# ---------------------------------------------------------------- targets and the report


def test_targets_are_the_fake_catalogs_on_the_test_stack(settings: Settings) -> None:
    assert targets(settings, "6pEWHaIhxOg", "q", "PLx") == FAKE_TARGETS
    real = settings.model_copy(update={"fake_youtube": False})
    assert targets(real, "6pEWHaIhxOg", "q", "PLx").video_id == "6pEWHaIhxOg"


def test_a_report_sums_up_its_checks() -> None:
    passed = Report("api", "2026-10-12T03:00:00.000Z", (Check("search", True, 12, "4 songs"),))
    assert passed.ok
    assert passed.message is None
    assert passed.as_status() == {"at": "2026-10-12T03:00:00.000Z", "ok": True, "message": None}
    failed = replace(passed, checks=(*passed.checks, Check("radio", False, 3, "x" * 900)))
    assert not failed.ok
    assert failed.message is not None
    assert failed.message.startswith("radio: xxx")
    assert len(failed.message) == MAX_MESSAGE
    assert json.loads(failed.detail_json())[1] == {
        "name": "radio",
        "ok": False,
        "durationMs": 3,
        "detail": "x" * 900,
    }


# ---------------------------------------------------------------- run_check


async def test_a_check_measures_its_duration(clock: FakeClock) -> None:
    async def work() -> str:
        clock.advance(0.25)
        return "fine"

    assert await run_check("x", clock, 5, work) == Check("x", True, 250, "fine")


@pytest.mark.parametrize(
    ("error", "detail"),
    [
        (CatalogParseError("search: no contents"), "layout changed: search: no contents"),
        (CatalogThrottled(), "YouTube Music is throttling requests"),
        (CatalogNotFound(), "Not found on YouTube Music"),
        (RuntimeError("boom"), "unexpected RuntimeError"),
    ],
)
async def test_a_failing_check_is_reported_not_raised(
    clock: FakeClock, error: Exception, detail: str
) -> None:
    async def work() -> str:
        raise error

    check = await run_check("x", clock, 5, work)
    assert (check.ok, check.detail) == (False, detail)


async def test_a_slow_check_times_out(clock: FakeClock) -> None:
    async def work() -> str:
        await anyio.sleep_forever()
        return "never"

    check = await run_check("x", clock, 0.01, work)
    assert (check.ok, check.detail) == (False, "timed out after 0.01 s")


async def test_details_are_one_short_line(clock: FakeClock) -> None:
    async def work() -> str:
        return "a\nb   c" + "d" * 500

    check = await run_check("x", clock, 5, work)
    assert check.detail.startswith("a b cddd")
    assert len(check.detail) == 200


# ---------------------------------------------------------------- the catalog side


async def test_the_catalog_canary_passes_on_the_fake_catalog(
    catalog: FakeMusicCatalog, clock: FakeClock
) -> None:
    report = await catalog_canary(catalog, clock).run()
    assert report.ok, report.message
    assert report.source == "api"
    assert report.ran_at == "2026-10-12T08:00:00.000Z"
    assert [c.name for c in report.checks] == ["search", "radio", "album", "playlist"]
    # The album page comes from the search result: no extra album search.
    assert catalog.calls == ["search_songs", "radio", "album", "playlist"]


async def test_every_catalog_check_runs_even_when_youtube_music_is_down(
    catalog: FakeMusicCatalog, clock: FakeClock
) -> None:
    catalog.fail_with = CatalogParseError("watch playlist: no tabs")
    report = await catalog_canary(catalog, clock).run()
    assert not report.ok
    assert [c.ok for c in report.checks] == [False, False, False, False]
    assert report.message is not None
    assert report.message.startswith("search: layout changed: watch playlist: no tabs; radio:")


class Empty(FakeMusicCatalog):
    """Answers, but with nothing in it (a silent layout change)."""

    async def search_songs(self, query: str, limit: int) -> list[CatalogTrack]:
        return []

    async def radio(self, video_id: str, limit: int) -> list[CatalogTrack]:
        return (await super().radio(video_id, limit))[:1]

    async def search_albums(self, query: str, limit: int) -> list[CatalogAlbumRef]:
        return []

    async def playlist(self, playlist_id: str) -> CatalogPlaylist:
        return replace(await super().playlist(playlist_id), tracks=())


async def test_empty_answers_fail(clock: FakeClock) -> None:
    report = await catalog_canary(Empty(), clock).run()
    assert [(c.name, c.ok, c.detail) for c in report.checks] == [
        ("search", False, "no songs found"),
        ("radio", False, "the radio has no other song"),
        ("album", False, "no album found"),
        ("playlist", False, "the playlist has no songs"),
    ]


class NoAlbumInSearch(FakeMusicCatalog):
    async def search_songs(self, query: str, limit: int) -> list[CatalogTrack]:
        songs = await super().search_songs(query, limit)
        return [replace(s, album=None) for s in songs]


async def test_the_album_comes_from_an_album_search_when_songs_have_none(
    clock: FakeClock,
) -> None:
    catalog = NoAlbumInSearch()
    report = await catalog_canary(catalog, clock).run()
    assert report.ok, report.message
    assert "search_albums" in catalog.calls


class EmptyAlbum(FakeMusicCatalog):
    async def album(self, browse_id: str):  # type: ignore[no-untyped-def]
        return replace(await super().album(browse_id), tracks=())


async def test_an_album_page_without_songs_fails(clock: FakeClock) -> None:
    report = await catalog_canary(EmptyAlbum(), clock).run()
    assert [c.detail for c in report.checks if not c.ok] == ["the album page has no songs"]


# ---------------------------------------------------------------- the download side


def leftovers(staging: LocalStagingStore) -> list[Path]:
    return [p for p in staging.root.rglob("*") if p.is_file()]


async def test_the_download_canary_downloads_checks_and_deletes(
    downloader: FakeDownloader, staging: LocalStagingStore, clock: FakeClock
) -> None:
    canary = DownloadCanary(downloader, staging, "Fk2Lp9QwXa1", clock, 5, token=lambda: "t1")
    report = await canary.run()
    assert report.ok, report.message
    assert report.source == "worker"
    assert report.checks[0].detail.startswith("format fake-opus, ")
    assert downloader.downloads == ["Fk2Lp9QwXa1"]
    assert not (staging.root / STAGING_ROOT / "t1").exists()
    assert leftovers(staging) == []


async def test_a_failed_download_is_reported_and_cleaned_up(
    staging: LocalStagingStore, clock: FakeClock
) -> None:
    async def never(_seconds: float) -> None:
        return None

    failing = FakeDownloader(
        staging,
        chunks=4,
        sleep=never,
        fail_after_bytes=1,
        fail_code=WorkerErrorCode.RATE_LIMITED_UPSTREAM,
    )
    report = await DownloadCanary(failing, staging, "Fk2Lp9QwXa1", clock, 5).run()
    assert not report.ok
    assert report.message == "download: rate_limited_upstream: fake failure"
    assert leftovers(staging) == []


async def test_an_invalid_video_id_never_reaches_the_downloader(
    downloader: FakeDownloader, staging: LocalStagingStore, clock: FakeClock
) -> None:
    report = await DownloadCanary(downloader, staging, "../etc", clock, 5).run()
    assert report.message == "download: invalid_video_id: invalid video id"
    assert downloader.downloads == []


class Lying:
    """Claims a result that does not match what is on disk."""

    def __init__(self, staging: LocalStagingStore, size: int, write: bool) -> None:
        self.staging = staging
        self.size = size
        self.write = write

    async def download(
        self,
        video_id: str,
        job_dir: str,
        on_progress: ProgressCallback,
        *,
        cookies: str | None = None,
    ) -> DownloadResult:
        final = f"{job_dir}/{video_id}.webm"
        if self.write:
            with self.staging.open_write(final) as out:
                out.write(b"abc")
        return DownloadResult(final, "251", "webm", "audio/webm", self.size, None)


@pytest.mark.parametrize(
    ("size", "write", "message"),
    [
        (0, True, "download: the download is empty"),
        (3, False, "download: the downloaded file is missing"),
        (4, True, "download: the file size does not match"),
    ],
)
async def test_a_bad_download_result_fails(
    staging: LocalStagingStore, clock: FakeClock, size: int, write: bool, message: str
) -> None:
    report = await DownloadCanary(
        Lying(staging, size, write), staging, "Fk2Lp9QwXa1", clock, 5
    ).run()
    assert report.message == message
    assert leftovers(staging) == []


class Undeletable(LocalStagingStore):
    def delete(self, rel: str) -> None:
        raise PermissionError(13, "Permission denied")


async def test_a_staging_dir_that_cannot_be_deleted_is_only_logged(
    tmp_path: Path, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    staging = Undeletable(tmp_path)
    downloader = FakeDownloader(staging, chunks=1, delay_s=0)
    report = await DownloadCanary(downloader, staging, "Fk2Lp9QwXa1", clock, 5).run()
    assert report.ok
    assert "could not delete canary/" in caplog.text


async def test_reports_are_stamped_when_the_run_ends(
    staging: LocalStagingStore, clock: FakeClock
) -> None:
    class Slow(FakeMusicCatalog):
        async def playlist(self, playlist_id: str) -> CatalogPlaylist:
            clock.advance(90)
            return await super().playlist(playlist_id)

    report = await catalog_canary(Slow(), clock).run()
    assert report.ran_at == "2026-10-12T08:01:30.000Z"

    class SlowDownloader(FakeDownloader):
        async def download(
            self,
            video_id: str,
            job_dir: str,
            on_progress: ProgressCallback,
            *,
            cookies: str | None = None,
        ) -> DownloadResult:
            clock.advance(30)
            return await super().download(video_id, job_dir, on_progress)

    slow = SlowDownloader(staging, chunks=1, delay_s=0)
    report = await DownloadCanary(slow, staging, "Fk2Lp9QwXa1", clock, 5).run()
    assert report.ran_at == "2026-10-12T08:02:00.000Z"
