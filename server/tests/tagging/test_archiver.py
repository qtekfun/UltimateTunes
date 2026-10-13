# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`TaggingArchiver` end to end with real stores, a fake internal API, respx for MusicBrainz
and covers, and a fake ffmpeg (plus a golden run with the real one when installed)."""

import hashlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from mutagen.oggopus import OggOpus

from tests.tagging.conftest import (
    FIXTURES,
    JOB_ID,
    LEASE_ID,
    STAGING_DIR,
    TRACK_ID,
    VIDEO,
    FakeApi,
    FakeRunner,
    conflict,
    copy_fixture,
    fake_ffmpeg,
    make_request,
    needs_ffmpeg,
    real_settings,
)
from ultimatetunes.core.clock import FakeClock
from ultimatetunes.errors import LeaseLost, NotFound, PathRejected, WorkerErrorCode
from ultimatetunes.settings import Settings
from ultimatetunes.tagging.archiver import TaggingArchiver, build_archiver, digest
from ultimatetunes.tagging.ffmpeg import Ffmpeg
from ultimatetunes.tagging.model import OPUS, ReplayGain
from ultimatetunes.tagging.musicbrainz import MUSICBRAINZ_URL
from ultimatetunes.tagging.settings import TaggingSettings
from ultimatetunes.tagging.tags import read_track_gain, write_tags
from ultimatetunes.worker.archiver import Archived, default_archiver
from ultimatetunes.worker.client import ApiUnavailableError
from ultimatetunes.worker.downloader import DownloadError

pytestmark = pytest.mark.anyio
LIB_PATH = "The Paper Lanterns/Lanterns at Dusk/04 - Paper Moons (Live).opus"
COVER = "The Paper Lanterns/Lanterns at Dusk/cover.jpg"
RELEASE = "4d6f8a0c-3e5a-4b7c-8f9a-1b3d5f7a9c02"
JPEG = b"\xff\xd8\xff\xe0cover"
OTHER_TRACK = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c001"


def clock_and_sleep() -> tuple[FakeClock, Callable[[float], Awaitable[None]]]:
    """A fake clock and a sleep that only advances it (a second MusicBrainz request waits
    for the next rate-limit token)."""
    clock = FakeClock()

    async def sleep(seconds: float) -> None:
        clock.advance(seconds)

    return clock, sleep


def archiver(runner: FakeRunner | None = None, **kwargs: Any) -> TaggingArchiver:
    clock, sleep = clock_and_sleep()
    return TaggingArchiver(
        TaggingSettings(), ffmpeg=fake_ffmpeg(runner), clock=clock, sleep=sleep, **kwargs
    )


@pytest.fixture
def online(web: respx.MockRouter, mb_search: dict[str, Any]) -> respx.MockRouter:
    web.get(MUSICBRAINZ_URL).respond(200, json=mb_search)
    web.get(f"https://coverartarchive.org/release/{RELEASE}/front-500").respond(
        200, content=JPEG, headers={"Content-Type": "image/jpeg"}
    )
    return web


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def test_a_download_is_tagged_registered_and_moved(
    tmp_path: Path, online: respx.MockRouter
) -> None:
    api = FakeApi()
    request = make_request(tmp_path, api)
    assert await archiver().archive(request) == Archived(TRACK_ID, LIB_PATH)
    body = api.registered[0]
    assert (body["jobId"], body["leaseId"], body["trackId"]) == (JOB_ID, LEASE_ID, TRACK_ID)
    assert body["stagingPath"] == f"{STAGING_DIR}/archive.opus"
    assert body["libraryPath"] == LIB_PATH
    archived = tmp_path / "music" / LIB_PATH
    assert body["file"] == {
        "format": "opus",
        "contentType": "audio/ogg",
        "sizeBytes": archived.stat().st_size,
        "durationMs": 262040,
        "bitRateKbps": 18,
        "sampleRateHz": 48000,
        "channels": 2,
        "sha256": sha(archived),
    }
    meta = body["metadata"]
    assert (meta["needsReview"], meta["musicbrainz"]["recordingId"]) == (
        False,
        "2b4d6f8a-1c3e-4a5b-9d7f-0e2c4a6b8d01",
    )
    assert meta["replayGain"] == {
        "trackGainDb": 3.8,
        "trackPeak": 0.101158,
        "albumGainDb": None,
        "albumPeak": None,
    }
    assert meta["coverPath"] == COVER
    assert meta["youtube"] == {
        "albumBrowseId": "MPREb_k3Vd9QmT2xL",
        "artistChannelId": "UCq8XbV1r0LwZ5mN3tYp7kQe",
    }
    assert (tmp_path / "music" / COVER).read_bytes() == JPEG
    tags: Any = OggOpus(archived)  # type: ignore[no-untyped-call]
    assert tags["TITLE"] == ["Paper Moons (Live)"]
    assert tags["REPLAYGAIN_TRACK_GAIN"] == ["3.80 dB"]
    assert api.replay_gain == []  # the album is not complete


async def test_an_m4a_download_becomes_an_m4a_archive(
    tmp_path: Path, online: respx.MockRouter
) -> None:
    api = FakeApi()
    runner = FakeRunner(codec="aac")
    request = make_request(tmp_path, api, source="tone.m4a")
    archived = await archiver(runner).archive(request)
    assert archived.library_path == LIB_PATH.replace(".opus", ".m4a")
    assert api.registered[0]["file"]["format"] == "m4a"
    remux = next(call for call in runner.calls if "-c:a" in call)
    assert remux[remux.index("-movflags") + 1] == "+faststart"


async def test_a_weak_match_keeps_youtube_data_and_the_thumbnail(
    tmp_path: Path, web: respx.MockRouter
) -> None:
    web.get(MUSICBRAINZ_URL).respond(200, json={"recordings": []})
    thumb = web.get(f"https://i.ytimg.com/vi/{VIDEO}/hqdefault.jpg").respond(
        200, content=JPEG, headers={"Content-Type": "image/jpeg"}
    )
    api = FakeApi()
    await archiver().archive(make_request(tmp_path, api, title="Paper/Moons", album=None))
    meta = api.registered[0]["metadata"]
    assert (meta["needsReview"], meta["album"], meta["matchScore"]) == (True, "Paper/Moons", None)
    assert (
        api.registered[0]["libraryPath"] == "The Paper Lanterns/Paper_Moons/04 - Paper_Moons.opus"
    )
    assert thumb.called


async def test_the_test_stack_never_goes_online(tmp_path: Path, web: respx.MockRouter) -> None:
    anything = web.route()
    api = FakeApi()
    built = build_archiver(Settings(fake_youtube=True))
    built.ffmpeg = fake_ffmpeg()
    await built.archive(make_request(tmp_path, api))
    assert not anything.called
    assert api.registered[0]["metadata"]["needsReview"] is True
    assert api.registered[0]["metadata"]["coverPath"] is None
    assert build_archiver(Settings()).lookups is True
    assert isinstance(default_archiver(Settings()), TaggingArchiver)


async def test_an_existing_cover_is_kept_and_not_fetched(
    tmp_path: Path, web: respx.MockRouter, mb_search: dict[str, Any]
) -> None:
    web.get(MUSICBRAINZ_URL).respond(200, json=mb_search)
    caa = web.route(host="coverartarchive.org")
    request = make_request(tmp_path, FakeApi())
    with request.library.open_write(COVER) as out:
        out.write(b"old cover")
    await archiver().archive(request)
    assert not caa.called
    assert (tmp_path / "music" / COVER).read_bytes() == b"old cover"


async def test_a_cover_that_appeared_meanwhile_is_kept(
    tmp_path: Path, online: respx.MockRouter
) -> None:
    class CoverMeanwhile(FakeApi):
        async def register_track(self, body: dict[str, Any]) -> dict[str, Any]:
            (tmp_path / "music" / COVER).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / "music" / COVER).write_bytes(b"theirs")
            return await super().register_track(body)

    await archiver().archive(make_request(tmp_path, CoverMeanwhile()))
    assert (tmp_path / "music" / COVER).read_bytes() == b"theirs"


async def test_a_merged_recording_never_reaches_the_library(
    tmp_path: Path, online: respx.MockRouter
) -> None:
    api = FakeApi(answers=[{"trackId": OTHER_TRACK, "merged": True, "album": None}])
    assert await archiver().archive(make_request(tmp_path, api)) == Archived(OTHER_TRACK, None)
    assert list((tmp_path / "music").iterdir()) == []


async def test_a_taken_path_gets_the_video_id(tmp_path: Path, online: respx.MockRouter) -> None:
    api = FakeApi(answers=[conflict()])
    archived = await archiver().archive(make_request(tmp_path, api))
    expected = f"The Paper Lanterns/Lanterns at Dusk/04 - Paper Moons (Live) ({VIDEO}).opus"
    assert archived.library_path == expected
    assert [b["libraryPath"] for b in api.registered] == [LIB_PATH, expected]
    assert (tmp_path / "music" / expected).is_file()


async def test_no_free_path_is_a_storage_error(tmp_path: Path, online: respx.MockRouter) -> None:
    api = FakeApi(answers=[conflict(), conflict()])
    with pytest.raises(DownloadError) as caught:
        await archiver().archive(make_request(tmp_path, api))
    assert (caught.value.code, caught.value.retryable) == (WorkerErrorCode.STORAGE_ERROR, False)


async def test_a_rejected_path_is_not_retried(tmp_path: Path, online: respx.MockRouter) -> None:
    api = FakeApi(answers=[PathRejected("libraryPath escapes /music")])
    with pytest.raises(DownloadError) as caught:
        await archiver().archive(make_request(tmp_path, api))
    assert (caught.value.code, caught.value.retryable) == (WorkerErrorCode.TAGGING_FAILED, False)


async def test_a_lost_lease_reaches_the_loop(tmp_path: Path, online: respx.MockRouter) -> None:
    api = FakeApi(answers=[LeaseLost("expired")])
    with pytest.raises(LeaseLost):
        await archiver().archive(make_request(tmp_path, api))


async def test_unsupported_codecs_fail_for_good(tmp_path: Path, web: respx.MockRouter) -> None:
    request = make_request(tmp_path, FakeApi(), source="vorbis.webm")
    with pytest.raises(DownloadError) as caught:
        await archiver(FakeRunner(codec="vorbis")).archive(request)
    assert (caught.value.code, caught.value.retryable) == (WorkerErrorCode.TAGGING_FAILED, False)


async def test_ffmpeg_failures_are_retryable_tagging_failures(
    tmp_path: Path, web: respx.MockRouter
) -> None:
    runner = FakeRunner()
    runner.fail = "ffprobe"
    with pytest.raises(DownloadError) as caught:
        await archiver(runner).archive(make_request(tmp_path, FakeApi()))
    assert (caught.value.code, caught.value.retryable) == (WorkerErrorCode.TAGGING_FAILED, True)


async def test_audio_without_duration_is_refused(tmp_path: Path, web: respx.MockRouter) -> None:
    class NoDuration(FakeRunner):
        async def __call__(self, args: Any, timeout_s: float) -> Any:
            result = await super().__call__(args, timeout_s)
            if Path(args[0]).name == "ffprobe":
                return type(result)(0, b'{"streams": [{"codec_name": "opus"}]}', b"")
            return result

    request = make_request(tmp_path, FakeApi())
    request = replace(request, download=replace(request.download, duration_ms=None))
    with pytest.raises(DownloadError, match="no duration"):
        await archiver(NoDuration()).archive(request)


async def test_a_retry_finds_its_own_file_in_place(
    tmp_path: Path, online: respx.MockRouter
) -> None:
    """The worker moved the file, then died before `complete`; the next attempt registers the
    same path, the api adopts the file (same SHA-256, no owner) and the move is skipped: no
    orphan, no ` (<videoId>)` duplicate."""
    first = make_request(tmp_path, FakeApi())
    await archiver().archive(first)  # moved, but `complete` never happened
    placed = tmp_path / "music" / LIB_PATH
    before = placed.read_bytes()
    first.staging.delete(STAGING_DIR)
    api = FakeApi(library=first.library)
    again = make_request(tmp_path, api)
    assert await archiver().archive(again) == Archived(TRACK_ID, LIB_PATH)
    assert [body["libraryPath"] for body in api.registered] == [LIB_PATH]
    assert placed.read_bytes() == before
    album = sorted(p.name for p in placed.parent.iterdir())
    assert album == ["04 - Paper Moons (Live).opus", "cover.jpg"]


async def test_a_file_owned_by_another_track_is_never_adopted(
    tmp_path: Path, online: respx.MockRouter
) -> None:
    first = make_request(tmp_path, FakeApi())
    await archiver().archive(first)
    first.staging.delete(STAGING_DIR)
    api = FakeApi(library=first.library, owned=[LIB_PATH])
    archived = await archiver().archive(make_request(tmp_path, api))
    assert archived.library_path == LIB_PATH.replace(").opus", f") ({VIDEO}).opus")


async def test_another_file_at_the_reserved_path_is_a_storage_error(
    tmp_path: Path, online: respx.MockRouter
) -> None:
    request = make_request(tmp_path, FakeApi())
    with request.library.open_write(LIB_PATH) as out:
        out.write(b"someone else")
    with pytest.raises(DownloadError) as caught:
        await archiver().archive(request)
    assert (caught.value.code, caught.value.retryable) == (WorkerErrorCode.STORAGE_ERROR, False)


# ---------------------------------------------------------------- album gain


def _album_answer(*tracks: tuple[str, str]) -> dict[str, Any]:
    return {
        "trackId": TRACK_ID,
        "albumId": "0199d6a2-4c1e-7b3a-9f10-2a6c8e01b004",
        "artistId": "0199d6a2-4c1e-7b3a-9f10-2a6c8e01a001",
        "merged": False,
        "album": {
            "totalTracks": len(tracks),
            "complete": True,
            "tracks": [{"trackId": t, "libraryPath": p} for t, p in tracks],
        },
    }


def _library_track(tmp_path: Path, fixture: str, rel: str, gain: ReplayGain | None) -> Path:
    from tests.tagging.conftest import sample_metadata  # noqa: PLC0415

    path = copy_fixture(fixture, tmp_path / "music" / rel)
    if gain is not None:
        write_tags(path, OPUS, sample_metadata(title="Other"), gain)
    return path


async def test_a_complete_album_gets_album_gain_everywhere(
    tmp_path: Path, online: respx.MockRouter
) -> None:
    other_opus = "The Paper Lanterns/Lanterns at Dusk/01 - Other.opus"
    other_m4a = "The Paper Lanterns/Lanterns at Dusk/02 - Third.m4a"
    third = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c002"
    _library_track(tmp_path, "tone.opus", other_opus, ReplayGain(-1.0, 0.5))
    _library_track(tmp_path, "tone-faststart.m4a", other_m4a, None)
    api = FakeApi(
        answers=[_album_answer((OTHER_TRACK, other_opus), (third, other_m4a), (TRACK_ID, LIB_PATH))]
    )
    runner = FakeRunner(lufs="-20.0", peak="-1.0")
    await archiver(runner).archive(make_request(tmp_path, api))
    album_runs = [c for c in runner.calls if c.count("-i") == 3]
    assert len(album_runs) == 1
    sent = dict(api.replay_gain)
    assert set(sent) == {OTHER_TRACK, third, TRACK_ID}
    assert sent[OTHER_TRACK]["replayGain"] == {
        "trackGainDb": -1.0,
        "trackPeak": 0.5,
        "albumGainDb": 2.0,
        "albumPeak": 0.891251,
    }
    assert sent[third]["replayGain"]["trackGainDb"] == 2.0  # measured: it had no tags
    for track_id, rel in ((OTHER_TRACK, other_opus), (TRACK_ID, LIB_PATH)):
        path = tmp_path / "music" / rel
        assert sent[track_id]["file"] == {"sizeBytes": path.stat().st_size, "sha256": sha(path)}
        assert sent[track_id]["jobId"] == JOB_ID
        tags: Any = OggOpus(path)  # type: ignore[no-untyped-call]
        assert tags["REPLAYGAIN_ALBUM_GAIN"] == ["2.00 dB"]
    leftovers = [p.name for p in (tmp_path / "music").rglob(".*")]
    assert leftovers == []


@pytest.mark.parametrize(
    "tracks",
    [
        [(OTHER_TRACK, "The Paper Lanterns/Lanterns at Dusk/01 - Missing.opus")],
        [(OTHER_TRACK, "The Paper Lanterns/Lanterns at Dusk/01 - Other.flac")],
        [(OTHER_TRACK, "../outside.opus")],
        [],  # this job's track is not in the list
    ],
)
async def test_album_gain_is_skipped_when_a_file_is_not_usable(
    tmp_path: Path, online: respx.MockRouter, tracks: list[tuple[str, str]]
) -> None:
    answer = _album_answer(*tracks)
    if tracks:
        answer["album"]["tracks"].append({"trackId": TRACK_ID, "libraryPath": LIB_PATH})
    api = FakeApi(answers=[answer])
    assert await archiver().archive(make_request(tmp_path, api)) == Archived(TRACK_ID, LIB_PATH)
    assert api.replay_gain == []


async def test_album_gain_failures_keep_the_track(
    tmp_path: Path, online: respx.MockRouter, caplog: pytest.LogCaptureFixture
) -> None:
    class AlbumFails(FakeRunner):
        async def __call__(self, args: Any, timeout_s: float) -> Any:
            if "-filter_complex" in args and args.count("-i") > 1:
                self.fail = "ffmpeg"
            try:
                return await super().__call__(args, timeout_s)
            finally:
                self.fail = None

    other = "The Paper Lanterns/Lanterns at Dusk/01 - Other.opus"
    _library_track(tmp_path, "tone.opus", other, ReplayGain(-1.0, 0.5))
    api = FakeApi(answers=[_album_answer((OTHER_TRACK, other), (TRACK_ID, LIB_PATH))])
    with caplog.at_level(logging.WARNING):
        result = await archiver(AlbumFails()).archive(make_request(tmp_path, api))
    assert result == Archived(TRACK_ID, LIB_PATH)
    assert api.replay_gain == []
    assert "album ReplayGain skipped" in caplog.text
    assert read_track_gain(tmp_path / "music" / other, OPUS) == ReplayGain(-1.0, 0.5)


async def test_digest_reads_in_chunks(tmp_path: Path) -> None:
    request = make_request(tmp_path, FakeApi())
    found = digest(request.staging, request.download.final_path)
    assert found.size_bytes == (FIXTURES / "tone.webm").stat().st_size
    assert found.sha256 == sha(FIXTURES / "tone.webm")


async def test_default_client_has_no_redirects() -> None:
    client = archiver().client_factory()
    async with client:
        assert client.follow_redirects is False
        assert isinstance(client, httpx.AsyncClient)


# ---------------------------------------------------------------- golden run (real ffmpeg)


@needs_ffmpeg
async def test_golden_archive_with_real_ffmpeg(
    tmp_path: Path, web: respx.MockRouter, mb_search: dict[str, Any]
) -> None:
    mb_search["recordings"][0]["length"] = 1000  # the tone lasts 1 s
    web.get(MUSICBRAINZ_URL).respond(200, json=mb_search)
    web.route(host="coverartarchive.org").respond(404)
    web.route(host="i.ytimg.com").respond(404)
    api = FakeApi()
    clock, sleep = clock_and_sleep()
    real = TaggingArchiver(
        real_settings(), ffmpeg=Ffmpeg(real_settings()), clock=clock, sleep=sleep
    )
    archived = await real.archive(make_request(tmp_path, api))
    path = tmp_path / "music" / str(archived.library_path)
    tags: Any = OggOpus(path)  # type: ignore[no-untyped-call]
    assert tags["MUSICBRAINZ_TRACKID"] == ["2b4d6f8a-1c3e-4a5b-9d7f-0e2c4a6b8d01"]
    gain = api.registered[0]["metadata"]["replayGain"]
    assert 1.0 < gain["trackGainDb"] < 5.0
    assert api.registered[0]["file"]["durationMs"] in range(950, 1050)
    assert api.registered[0]["file"]["sha256"] == sha(path)


@pytest.mark.parametrize("failure", [ApiUnavailableError("api down"), NotFound("no track")])
async def test_a_replay_gain_report_that_fails_is_only_logged(
    tmp_path: Path,
    online: respx.MockRouter,
    caplog: pytest.LogCaptureFixture,
    failure: Exception,
) -> None:
    class PutFails(FakeApi):
        async def update_replay_gain(self, track_id: str, body: dict[str, Any]) -> None:
            raise failure

    other = "The Paper Lanterns/Lanterns at Dusk/01 - Other.opus"
    _library_track(tmp_path, "tone.opus", other, ReplayGain(-1.0, 0.5))
    api = PutFails(answers=[_album_answer((OTHER_TRACK, other), (TRACK_ID, LIB_PATH))])
    with caplog.at_level(logging.WARNING):
        result = await archiver().archive(make_request(tmp_path, api))
    assert result == Archived(TRACK_ID, LIB_PATH)
    assert caplog.text.count("not reported") == 2


async def test_a_lost_lease_during_album_gain_stops_the_job(
    tmp_path: Path, online: respx.MockRouter
) -> None:
    class LeaseGone(FakeApi):
        async def update_replay_gain(self, track_id: str, body: dict[str, Any]) -> None:
            raise LeaseLost("expired")

    other = "The Paper Lanterns/Lanterns at Dusk/01 - Other.opus"
    _library_track(tmp_path, "tone.opus", other, ReplayGain(-1.0, 0.5))
    api = LeaseGone(answers=[_album_answer((OTHER_TRACK, other), (TRACK_ID, LIB_PATH))])
    with pytest.raises(LeaseLost):
        await archiver().archive(make_request(tmp_path, api))
    assert not (tmp_path / "music" / LIB_PATH).exists()
