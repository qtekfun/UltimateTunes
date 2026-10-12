# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared helpers of the tagging tests: fixture files, a fake `WorkerApi`, a fake ffmpeg."""

import json
import shutil
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
import respx

from ultimatetunes.core.storage import LocalLibraryStore, LocalStagingStore
from ultimatetunes.errors import Conflict
from ultimatetunes.tagging.ffmpeg import Ffmpeg, ProcessResult
from ultimatetunes.tagging.model import M4A, OPUS, MusicBrainzIds, TrackMetadata
from ultimatetunes.tagging.settings import TaggingSettings
from ultimatetunes.worker.archiver import ArchiveRequest
from ultimatetunes.worker.client import ClaimedJob, JobHints, JobOutcome, LeaseInfo
from ultimatetunes.worker.downloader import DownloadProgress, DownloadResult

FIXTURES = Path(__file__).parent / "fixtures"
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(
    FFMPEG is None or FFPROBE is None, reason="ffmpeg/ffprobe not installed"
)
JOB_ID = "0199d6a2-4c1e-7b3a-9f10-2a6c8e019001"
TRACK_ID = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c005"
LEASE_ID = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01aa01"
VIDEO = "Qx7Lm2pZ0aB"
STAGING_DIR = f"{JOB_ID}/1"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def mb_search() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / "musicbrainz_search.json").read_text())
    return data


@pytest.fixture
def web() -> Iterator[respx.MockRouter]:
    """Every outbound request of a test goes through this router (none reaches the network)."""
    with respx.mock(assert_all_called=False) as router:
        yield router


def real_settings() -> TaggingSettings:
    return TaggingSettings(ffmpeg_path=Path(FFMPEG or "ffmpeg"), ffprobe_path=Path(FFPROBE or "x"))


def sample_metadata(**changes: Any) -> TrackMetadata:
    fields: dict[str, Any] = {
        "title": "Paper Moons (Live)",
        "artist": "The Paper Lanterns",
        "artist_sort": "Paper Lanterns, The",
        "album_artist": "The Paper Lanterns",
        "album": "Lanterns at Dusk",
        "track_number": 4,
        "disc_number": 1,
        "total_tracks": 9,
        "total_discs": 1,
        "year": 2024,
        "genre": "Indie Pop",
        "release_type": "live",
        "isrc": "XXA012400004",
        "musicbrainz": MusicBrainzIds(
            recording_id="2b4d6f8a-1c3e-4a5b-9d7f-0e2c4a6b8d01",
            track_id="3e4f5a6b-7c8d-4e9f-8a0b-1c2d3e4f5a07",
            release_id="4d6f8a0c-3e5a-4b7c-8f9a-1b3d5f7a9c02",
            release_group_id="7c8d9e0f-1a2b-4c3d-9e4f-5a6b7c8d9e04",
            artist_id="5f0c2d6e-8b1a-4c3d-9e7f-1a2b3c4d5e01",
            album_artist_id="5f0c2d6e-8b1a-4c3d-9e7f-1a2b3c4d5e01",
        ),
        "album_browse_id": "MPREb_k3Vd9QmT2xL",
        "artist_channel_id": "UCq8XbV1r0LwZ5mN3tYp7kQe",
        "needs_review": False,
        "match_score": 0.94,
    }
    return TrackMetadata(**(fields | changes))


def copy_fixture(name: str, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES / name, target)
    return target


class FakeApi:
    """The library side of the internal worker API, as the worker sees it."""

    def __init__(self, *, answers: Sequence[dict[str, Any] | Exception] = ()) -> None:
        self.answers = list(answers)
        self.registered: list[dict[str, Any]] = []
        self.replay_gain: list[tuple[str, dict[str, Any]]] = []

    async def register_track(self, body: dict[str, Any]) -> dict[str, Any]:
        self.registered.append(body)
        if self.answers:
            answer = self.answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return {
            "trackId": body["trackId"],
            "albumId": "0199d6a2-4c1e-7b3a-9f10-2a6c8e01b004",
            "artistId": "0199d6a2-4c1e-7b3a-9f10-2a6c8e01a001",
            "merged": False,
            "album": {
                "totalTracks": 9,
                "complete": False,
                "tracks": [{"trackId": body["trackId"], "libraryPath": body["libraryPath"]}],
            },
        }

    async def update_replay_gain(self, track_id: str, body: dict[str, Any]) -> None:
        self.replay_gain.append((track_id, body))

    # The rest of `WorkerApi` is the loop's business.
    async def claim(self, worker_id: str, lease_s: int) -> Any:
        raise NotImplementedError

    async def heartbeat(self, job: ClaimedJob, lease_s: int) -> LeaseInfo:
        raise NotImplementedError

    async def progress(self, job: ClaimedJob, state: str, report: DownloadProgress) -> LeaseInfo:
        raise NotImplementedError

    async def complete(self, job: ClaimedJob, **fields: Any) -> JobOutcome:
        raise NotImplementedError

    async def fail(self, job: ClaimedJob, **fields: Any) -> JobOutcome:
        raise NotImplementedError

    async def report_status(self, worker_id: str, **fields: Any) -> list[str]:
        raise NotImplementedError


def conflict() -> Conflict:
    return Conflict("libraryPath is held by another track")


def make_job(**hints: Any) -> ClaimedJob:
    fields: dict[str, Any] = {
        "title": "Paper Moons (Live)",
        "artist": "The Paper Lanterns",
        "album": "Lanterns at Dusk",
        "album_browse_id": "MPREb_k3Vd9QmT2xL",
        "artist_channel_id": "UCq8XbV1r0LwZ5mN3tYp7kQe",
        "duration_ms": 1000,
        "year": 2024,
        "track_number": 4,
        "thumbnail_url": f"https://i.ytimg.com/vi/{VIDEO}/hqdefault.jpg",
    }
    return ClaimedJob(
        job_id=JOB_ID,
        track_id=TRACK_ID,
        video_id=VIDEO,
        attempt=1,
        max_attempts=3,
        staging_dir=STAGING_DIR,
        hints=JobHints(**(fields | hints)),
        lease_id=LEASE_ID,
        heartbeat_s=20,
    )


def make_request(
    tmp_path: Path, api: FakeApi, *, source: str = "tone.webm", **hints: Any
) -> ArchiveRequest:
    staging = LocalStagingStore(tmp_path / "staging")
    library = LocalLibraryStore(tmp_path / "music")
    (tmp_path / "music").mkdir(exist_ok=True)
    ext = source.rsplit(".", 1)[1]
    final = f"{STAGING_DIR}/{VIDEO}.{ext}"
    copy_fixture(source, staging.root / final)
    download = DownloadResult(
        final, "251", ext, "audio/webm", (FIXTURES / source).stat().st_size, 1000
    )
    return ArchiveRequest(make_job(**hints), download, api, staging, library)


PROBES = {
    "opus": {"codec_name": "opus", "sample_rate": "48000", "channels": 2, "duration": "262.040"},
    "aac": {"codec_name": "aac", "sample_rate": "44100", "channels": 2, "duration": "262.040"},
    "vorbis": {"codec_name": "vorbis", "sample_rate": "48000", "channels": 2},
}
ARCHIVES = {OPUS.muxer: "tone.opus", M4A.muxer: "tone-faststart.m4a"}


def ebur128(lufs: str, peak: str) -> bytes:
    return (
        "[Parsed_ebur128_0 @ 0x1] Summary:\n\n  Integrated loudness:\n"
        f"    I:         {lufs} LUFS\n    Threshold: -31.8 LUFS\n\n  True peak:\n"
        f"    Peak:      {peak} dBFS\n"
    ).encode()


class FakeRunner:
    """Stands in for ffmpeg/ffprobe: probes by file name, remuxes by copying the archive
    fixture, measures canned loudness. Records every argument list."""

    def __init__(self, *, codec: str = "opus", lufs: str = "-21.8", peak: str = "-19.9") -> None:
        self.calls: list[list[str]] = []
        self.codec = codec
        self.lufs = lufs
        self.peak = peak
        self.fail: str | None = None

    async def __call__(self, args: Sequence[str], timeout_s: float) -> ProcessResult:
        self.calls.append(list(args))
        tool = Path(args[0]).name
        if self.fail == tool:
            return ProcessResult(1, b"", b"boom")
        target = Path(args[-1].removeprefix("file:"))
        if tool == "ffprobe":
            codec = self.codec
            if target.name.startswith("archive."):
                codec = "opus" if target.suffix == ".opus" else "aac"
            body = {"streams": [PROBES[codec]], "format": {"bit_rate": "18182"}}
            return ProcessResult(0, json.dumps(body).encode(), b"")
        if "-filter_complex" in args:
            return ProcessResult(0, b"", ebur128(self.lufs, self.peak))
        muxer = args[args.index("-f") + 1]
        copy_fixture(ARCHIVES[muxer], target)
        return ProcessResult(0, b"", b"")


def fake_ffmpeg(runner: FakeRunner | None = None) -> Ffmpeg:
    return Ffmpeg(TaggingSettings(), runner or FakeRunner())
