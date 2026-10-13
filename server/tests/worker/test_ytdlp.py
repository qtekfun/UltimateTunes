# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""YtDlpDownloader: command line, output parsing, error classes, and real subprocess runs
against a stand-in zipapp (`fixtures/fake_ytdlp.py`). Nothing reaches the network."""

import itertools
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import anyio
import pytest
from pydantic import ValidationError

from ultimatetunes.core.limits import DownloadLimits
from ultimatetunes.core.storage import LocalStagingStore
from ultimatetunes.errors import WorkerErrorCode
from ultimatetunes.worker import ytdlp
from ultimatetunes.worker.downloader import DownloadError, DownloadProgress
from ultimatetunes.worker.settings import WorkerSettings
from ultimatetunes.worker.ytdlp import (
    FORMAT_SELECTOR,
    YtDlpDownloader,
    build_args,
    classify,
    iter_lines,
    minimal_env,
    parse_progress,
    parse_result,
    redact,
)

pytestmark = pytest.mark.anyio
FIXTURES = Path(__file__).parent / "fixtures"
FAKE_ZIPAPP = FIXTURES / "fake_ytdlp.py"
JOB_DIR = "0199d6a2-4c1e-7b3a-9f10-2a6c8e019001/1"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class Zipapp:
    def __init__(self, path: Path) -> None:
        self.path = path

    def current_zipapp(self) -> Path:
        return self.path


@pytest.fixture
def staging(tmp_path: Path) -> LocalStagingStore:
    root = tmp_path / "staging"
    root.mkdir()
    return LocalStagingStore(root)


def downloader(
    staging: LocalStagingStore, zipapp: Path = FAKE_ZIPAPP, **settings: object
) -> YtDlpDownloader:
    return YtDlpDownloader(staging, WorkerSettings(**settings), Zipapp(zipapp))  # type: ignore[arg-type]


class Recorder:
    def __init__(self) -> None:
        self.reports: list[DownloadProgress] = []

    async def __call__(self, report: DownloadProgress) -> None:
        self.reports.append(report)


# ---------------------------------------------------------------- pure parts


def test_the_command_line_is_a_list_with_the_id_after_double_dash(tmp_path: Path) -> None:
    args = build_args(
        python="/usr/bin/python3",
        zipapp=Path("/opt/ytdlp/current/yt-dlp"),
        deno=Path("/usr/local/bin/deno"),
        clients="default",
        out_dir=tmp_path,
        video_id="-x7Lm2pZ0aB",
        limits=DownloadLimits(max_track_duration_s=1200, max_download_bytes=50_000_000),
    )
    assert args[:4] == ["/usr/bin/python3", "-I", "-S", "/opt/ytdlp/current/yt-dlp"]
    assert args[-2:] == ["--", "https://www.youtube.com/watch?v=-x7Lm2pZ0aB"]
    pairs = dict(itertools.pairwise(args))
    assert pairs["--format"] == FORMAT_SELECTOR
    assert pairs["--fixup"] == "never"
    assert pairs["--js-runtimes"] == "deno:/usr/local/bin/deno"
    assert pairs["--extractor-args"] == "youtube:player_client=default"
    assert pairs["--output"] == "-x7Lm2pZ0aB.%(ext)s"
    # Abuse limits: a strict duration filter (an unknown duration does not pass) and a size cap.
    assert pairs["--match-filter"] == "duration<=1200"
    assert pairs["--max-filesize"] == "50000000"
    assert args.index("--match-filter") < args.index("--")
    # The screen output stays on, so a skip on a limit can be told apart from a bug.
    assert "--no-quiet" in args
    for flag in ("--ignore-config", "--no-remote-components", "--no-js-runtimes", "--newline"):
        assert flag in args


def test_the_limits_must_be_positive_integers(tmp_path: Path) -> None:
    broken = DownloadLimits.model_construct(max_track_duration_s=0, max_download_bytes=1)
    with pytest.raises(ValueError, match="positive"):
        build_args(
            python="python3",
            zipapp=Path("/z"),
            deno=Path("/d"),
            clients="default",
            out_dir=tmp_path,
            video_id="OkWebm00001",
            limits=broken,
        )


def test_the_environment_carries_no_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UT_WORKER_TOKEN", "secret")
    env = minimal_env(tmp_path)
    assert "UT_WORKER_TOKEN" not in env
    assert env["HOME"] == str(tmp_path)
    assert env["DENO_NO_UPDATE_CHECK"] == "1"


def test_recorded_output_lines() -> None:
    lines = (FIXTURES / "ytdlp_output.txt").read_text(encoding="utf-8").splitlines()
    progress = [p for p in map(parse_progress, lines) if p is not None]
    results = [r for r in map(parse_result, lines) if r is not None]
    assert [(p.status, p.downloaded_bytes, p.total_bytes, p.ext) for p in progress] == [
        ("downloading", 1024, 4310772, "webm"),
        ("downloading", 1810524, 4310772, "webm"),
        ("downloading", 2048, None, "m4a"),
        ("finished", 4310772, 4310772, "webm"),
    ]
    assert progress[0].tmpfilename == "/staging/J/1/Qx7Lm2pZ0aB.webm.part"
    assert progress[0].format_id == "251"
    assert progress[3].tmpfilename is None
    assert len(results) == 1
    assert results[0].filepath == "/staging/J/1/Qx7Lm2pZ0aB.webm"
    assert results[0].duration_s == pytest.approx(262.04)
    assert parse_progress('UTP {"status": "downloading"}') is not None
    assert parse_result('UTF {"filepath": "/x", "duration": "long"}') is not None


def test_errors_are_classified_like_the_spike_table() -> None:
    cases = {
        "ERROR: [youtube] x: Video unavailable": WorkerErrorCode.VIDEO_UNAVAILABLE,
        "ERROR: [youtube] x: Sign in to confirm your age": WorkerErrorCode.VIDEO_UNAVAILABLE,
        "ERROR: [youtube] x: Sign in to confirm you're not a bot": (
            WorkerErrorCode.RATE_LIMITED_UPSTREAM
        ),
        "ERROR: unable to download video data: HTTP Error 429: Too Many Requests": (
            WorkerErrorCode.RATE_LIMITED_UPSTREAM
        ),
        "ERROR: [youtube] x: Requested format is not available": WorkerErrorCode.EXTRACTOR_ERROR,
        "ERROR: [youtube] x: n challenge solving failed": WorkerErrorCode.EXTRACTOR_ERROR,
        "ERROR: unable to download video data: HTTP Error 403: Forbidden": (
            WorkerErrorCode.NETWORK_ERROR
        ),
        "ERROR: The read operation timed out": WorkerErrorCode.NETWORK_ERROR,
        "ERROR: [Errno 28] No space left on device": WorkerErrorCode.STORAGE_ERROR,
        "ERROR: something nobody expected": WorkerErrorCode.INTERNAL_ERROR,
    }
    for line, code in cases.items():
        error = classify([line], 1)
        assert error.code == code, line
    usage = classify([], 2)
    assert (usage.code, usage.retryable) == (WorkerErrorCode.INTERNAL_ERROR, False)
    assert usage.message == "yt-dlp exited with 2"
    usage_with_text = classify(["ERROR: no such option"], 2)
    assert (usage_with_text.code, usage_with_text.retryable) == (
        WorkerErrorCode.INTERNAL_ERROR,
        False,
    )
    assert classify([], 1).retryable


def test_log_lines_never_carry_urls() -> None:
    line = "ERROR: unable to download https://rr1---sn.googlevideo.com/videoplayback?ip=1.2.3.4"
    assert redact(line) == "ERROR: unable to download <url>"
    assert len(redact("x" * 2000)) == 500


async def test_lines_are_split_and_capped() -> None:
    async def chunks() -> AsyncIterator[bytes]:
        yield b"one\r\ntw"
        yield b"o\n" + b"x" * (ytdlp.MAX_LINE + 10)
        yield b"\nlast"

    seen = [line async for line in iter_lines(chunks())]
    assert seen[:2] == ["one", "two"]
    assert len(seen[2]) <= ytdlp.MAX_LINE
    assert seen[3] == "last"


def test_player_clients_default_and_validation() -> None:
    # Empty (compose forwards `${UT_YTDLP_PLAYER_CLIENTS:-}` unset) keeps the default.
    assert WorkerSettings().ytdlp_player_clients == "web_safari,tv"
    assert WorkerSettings(ytdlp_player_clients="").ytdlp_player_clients == "web_safari,tv"
    assert WorkerSettings(ytdlp_player_clients="  ").ytdlp_player_clients == "web_safari,tv"
    assert WorkerSettings(ytdlp_player_clients="mweb,tv").ytdlp_player_clients == "mweb,tv"
    with pytest.raises(ValidationError):
        WorkerSettings(ytdlp_player_clients="Bad Client")


def test_the_ladder_drops_duplicates_and_empties(staging: LocalStagingStore) -> None:
    assert downloader(staging).ladder() == ["web_safari,tv", "default"]
    same = downloader(staging, ytdlp_player_clients="tv", ytdlp_fallback_clients="tv")
    assert same.ladder() == ["tv"]
    assert downloader(staging, ytdlp_player_clients="tv", ytdlp_fallback_clients="").ladder() == [
        "tv"
    ]


# ---------------------------------------------------------------- real subprocess runs


async def test_a_download_reports_progress_then_finishes(staging: LocalStagingStore) -> None:
    recorder = Recorder()
    result = await downloader(staging).download("OkWebm00001", JOB_DIR, recorder)
    final = f"{JOB_DIR}/OkWebm00001.webm"
    assert (result.final_path, result.format_id, result.ext) == (final, "251", "webm")
    assert (result.content_type, result.duration_ms) == ("audio/webm", 2500)
    assert result.size_bytes == staging.size(final) == 4100
    assert [r.downloaded_bytes for r in recorder.reports] == [1025, 2050, 3075, 4100, 4100]
    assert all(r.expected_size == 4100 for r in recorder.reports)
    assert all(r.part_path == f"{final}.part" and r.final_path == final for r in recorder.reports)
    assert [r.finished for r in recorder.reports] == [False] * 4 + [True]
    assert all(r.progressive and r.content_type == "audio/webm" for r in recorder.reports)
    assert not staging.exists(f"{final}.part")


async def test_m4a_is_served_only_once_finished(staging: LocalStagingStore) -> None:
    recorder = Recorder()
    result = await downloader(staging).download("M4aAudio001", JOB_DIR, recorder)
    assert (result.ext, result.content_type, result.format_id) == ("m4a", "audio/mp4", "140")
    assert not any(r.progressive for r in recorder.reports)


async def test_an_unknown_size_stays_null(staging: LocalStagingStore) -> None:
    recorder = Recorder()
    await downloader(staging).download("NoSizeKnown", JOB_DIR, recorder)
    assert all(r.expected_size is None for r in recorder.reports)


# `clienta` is the first rung (it fails in the fixture), `clientb` the working fallback.
def laddered(
    staging: LocalStagingStore, *, player: str = "clienta", fallback: str = "clientb"
) -> YtDlpDownloader:
    return YtDlpDownloader(
        staging,
        WorkerSettings(ytdlp_player_clients=player, ytdlp_fallback_clients=fallback),
        Zipapp(FAKE_ZIPAPP),
    )


async def test_the_client_ladder_retries_extraction_failures(staging: LocalStagingStore) -> None:
    recorder = Recorder()
    result = await laddered(staging).download("LadderFmt01", JOB_DIR, recorder)
    assert result.final_path == f"{JOB_DIR}/LadderFmt01.webm"
    no_fallback = laddered(staging, fallback="")
    with pytest.raises(DownloadError) as caught:
        await no_fallback.download("LadderFmt01", JOB_DIR, recorder)
    assert caught.value.code == WorkerErrorCode.EXTRACTOR_ERROR


async def test_a_403_on_the_first_client_takes_the_ladder(staging: LocalStagingStore) -> None:
    # A 403 (network_error) before any byte on `clienta` falls through to `clientb`.
    recorder = Recorder()
    result = await laddered(staging).download("Forbid403A1", JOB_DIR, recorder)
    assert result.final_path == f"{JOB_DIR}/Forbid403A1.webm"
    assert result.size_bytes == staging.size(result.final_path)


async def test_a_403_on_every_client_fails_the_job_cleanly(staging: LocalStagingStore) -> None:
    with pytest.raises(DownloadError) as caught:
        await laddered(staging).download("Block403All", JOB_DIR, Recorder())
    assert (caught.value.code, caught.value.retryable) == (WorkerErrorCode.NETWORK_ERROR, True)
    # Nothing was left behind as a usable file.
    assert not staging.exists(f"{JOB_DIR}/Block403All.webm")


async def test_a_short_final_file_is_rejected_not_archived(staging: LocalStagingStore) -> None:
    # yt-dlp announced the full size but the file ended short: a truncated download must never
    # be returned as complete (SPEC section 11, abort-on-size-mismatch).
    with pytest.raises(DownloadError) as caught:
        await downloader(staging).download("ShortFile01", JOB_DIR, Recorder())
    assert (caught.value.code, caught.value.retryable) == (WorkerErrorCode.NETWORK_ERROR, True)
    assert "not the announced" in caught.value.message


@pytest.mark.parametrize(
    ("video", "code", "retryable"),
    [
        ("GoneVideo01", WorkerErrorCode.VIDEO_UNAVAILABLE, False),
        ("BotWall0001", WorkerErrorCode.RATE_LIMITED_UPSTREAM, True),
        ("UsageError1", WorkerErrorCode.INTERNAL_ERROR, False),
        ("DiesMidway1", WorkerErrorCode.NETWORK_ERROR, True),
        ("NoResultL01", WorkerErrorCode.INTERNAL_ERROR, True),
        ("MkvFormat01", WorkerErrorCode.FORMAT_UNAVAILABLE, False),
        ("EscapeDir01", WorkerErrorCode.INTERNAL_ERROR, False),
        ("DotDotName1", WorkerErrorCode.INTERNAL_ERROR, False),
    ],
)
async def test_failures(
    staging: LocalStagingStore, video: str, code: WorkerErrorCode, retryable: bool
) -> None:
    with pytest.raises(DownloadError) as caught:
        await downloader(staging).download(video, JOB_DIR, Recorder())
    assert (caught.value.code, caught.value.retryable) == (code, retryable)


async def test_a_mid_download_failure_does_not_take_the_ladder(
    staging: LocalStagingStore,
) -> None:
    recorder = Recorder()
    with pytest.raises(DownloadError):
        await downloader(staging).download("DiesMidway1", JOB_DIR, recorder)
    assert len(recorder.reports) == 1


async def test_a_hung_download_times_out_and_is_killed(staging: LocalStagingStore) -> None:
    slow = downloader(staging, ytdlp_timeout_s=0.5)
    with pytest.raises(DownloadError) as caught:
        await slow.download("HangForever", JOB_DIR, Recorder())
    assert caught.value.code == WorkerErrorCode.NETWORK_ERROR


async def test_cancelling_the_job_kills_the_process(staging: LocalStagingStore) -> None:
    started: list[float] = []
    with anyio.move_on_after(0.5):
        started.append(1.0)
        await downloader(staging).download("HangForever", JOB_DIR, Recorder())
    assert started == [1.0]


async def test_bad_ids_and_missing_installs_never_start_a_process(
    staging: LocalStagingStore, tmp_path: Path
) -> None:
    with pytest.raises(DownloadError) as caught:
        await downloader(staging).download("--exec=rm -", JOB_DIR, Recorder())
    assert caught.value.code == WorkerErrorCode.INVALID_VIDEO_ID
    missing = downloader(staging, zipapp=tmp_path / "nothing")
    with pytest.raises(DownloadError, match="not installed"):
        await missing.download("OkWebm00001", JOB_DIR, Recorder())


async def test_an_unwritable_staging_directory_is_a_storage_error(
    staging: LocalStagingStore,
) -> None:
    (staging.root / "blocked").write_text("a file, not a directory")
    with pytest.raises(DownloadError) as caught:
        await downloader(staging).download("OkWebm00001", "blocked/1", Recorder())
    assert caught.value.code == WorkerErrorCode.STORAGE_ERROR


async def test_a_vanished_file_is_a_storage_error(
    staging: LocalStagingStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    def gone(_rel: str) -> int:
        raise FileNotFoundError

    monkeypatch.setattr(staging, "size", gone)
    with pytest.raises(DownloadError) as caught:
        await downloader(staging).download("OkWebm00001", JOB_DIR, Recorder())
    assert caught.value.code == WorkerErrorCode.STORAGE_ERROR


async def test_the_current_link_is_resolved_once_per_download(
    staging: LocalStagingStore, tmp_path: Path
) -> None:
    link = tmp_path / "current"
    link.symlink_to(FAKE_ZIPAPP)
    seen: list[list[str]] = []

    async def runner(args: list[str], env: dict[str, str]) -> Any:
        seen.append(args)
        return await ytdlp._open(args, env)

    resolving = YtDlpDownloader(staging, WorkerSettings(), Zipapp(link), runner=runner)
    await resolving.download("OkWebm00001", JOB_DIR, Recorder())
    assert seen[0][3] == str(FAKE_ZIPAPP.resolve())


# ---------------------------------------------------------------- abuse limits

SMALL = DownloadLimits.model_construct(max_track_duration_s=1800, max_download_bytes=10_000)


def limited(staging: LocalStagingStore) -> YtDlpDownloader:
    return YtDlpDownloader(staging, WorkerSettings(), Zipapp(FAKE_ZIPAPP), limits=SMALL)


@pytest.mark.parametrize("video", ["TooLongVid1", "HugeFile001"])
async def test_a_video_skipped_on_a_limit_fails_for_good(
    staging: LocalStagingStore, video: str
) -> None:
    recorder = Recorder()
    with pytest.raises(DownloadError) as caught:
        await limited(staging).download(video, JOB_DIR, recorder)
    assert (caught.value.code, caught.value.retryable) == (WorkerErrorCode.VIDEO_UNAVAILABLE, False)
    assert "larger than this server allows" in caught.value.message
    assert recorder.reports == []


async def test_a_silent_exit_without_a_file_is_retried(staging: LocalStagingStore) -> None:
    with pytest.raises(DownloadError) as caught:
        await limited(staging).download("SilentExit1", JOB_DIR, Recorder())
    assert (caught.value.code, caught.value.retryable) == (WorkerErrorCode.INTERNAL_ERROR, True)


async def test_a_download_growing_past_the_size_limit_is_stopped(
    staging: LocalStagingStore,
) -> None:
    recorder = Recorder()
    with pytest.raises(DownloadError) as caught:
        await limited(staging).download("GrowsHuge01", JOB_DIR, recorder)
    assert (caught.value.code, caught.value.retryable) == (WorkerErrorCode.VIDEO_UNAVAILABLE, False)
    assert "10000 bytes" in caught.value.message
    # Stopped at the first report over the limit, before yt-dlp finished.
    assert all(r.downloaded_bytes <= 10_000 for r in recorder.reports)
    assert not staging.exists(f"{JOB_DIR}/GrowsHuge01.webm")


async def test_an_announced_size_over_the_limit_is_stopped(staging: LocalStagingStore) -> None:
    # The size is known up front but yt-dlp did not skip it (e.g. an older yt-dlp).
    tight = DownloadLimits.model_construct(max_track_duration_s=1800, max_download_bytes=4000)
    downloader_ = YtDlpDownloader(staging, WorkerSettings(), Zipapp(FAKE_ZIPAPP), limits=tight)
    with pytest.raises(DownloadError) as caught:
        await downloader_.download("OkWebm00001", JOB_DIR, Recorder())
    assert caught.value.code == WorkerErrorCode.VIDEO_UNAVAILABLE


async def test_the_default_limits_let_ordinary_songs_through(staging: LocalStagingStore) -> None:
    result = await downloader(staging).download("HugeFile001", JOB_DIR, Recorder())
    assert result.size_bytes == 4100 * 8
