# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""ffmpeg/ffprobe: argument lists, output parsing, failures; golden runs on the generated
tones when ffmpeg is installed (stream copy proven by identical packet hashes)."""

import json
import math
import shutil
import subprocess  # nosec B404 - tests only, argument lists
from collections.abc import Sequence
from pathlib import Path

import anyio
import pytest

from tests.tagging.conftest import (
    FIXTURES,
    FakeRunner,
    copy_fixture,
    ebur128,
    needs_ffmpeg,
    real_settings,
)
from ultimatetunes.tagging.ffmpeg import (
    Ffmpeg,
    FfmpegError,
    Loudness,
    Probe,
    ProcessResult,
    loudness_args,
    parse_loudness,
    parse_probe,
    probe_args,
    remux_args,
    run_process,
)
from ultimatetunes.tagging.model import M4A, OPUS, ArchiveKind
from ultimatetunes.tagging.settings import TaggingSettings

pytestmark = pytest.mark.anyio
FF = Path("/usr/bin/ffmpeg")


def test_remux_is_a_stream_copy_into_the_archive_container() -> None:
    args = remux_args(FF, Path("/s/a.webm"), Path("/s/archive.opus"), OPUS)
    assert args[0] == "/usr/bin/ffmpeg"
    assert args[args.index("-i") + 1] == "file:/s/a.webm"
    assert args[args.index("-c:a") + 1] == "copy"
    assert args[args.index("-f") + 1] == "matroska"  # the input's demuxer, forced
    assert args[len(args) - 1 - args[::-1].index("-f") + 1] == "ogg"  # the output's muxer
    assert args[-1] == "file:/s/archive.opus"
    assert "-nostdin" in args
    assert "-n" in args  # never overwrite
    m4a = remux_args(FF, Path("/s/a.m4a"), Path("/s/archive.m4a"), M4A)
    assert m4a[m4a.index("-movflags") + 1] == "+faststart"
    assert m4a[m4a.index("-f") + 1] == "mov"
    assert m4a[-3:-1] == ["-f", "mp4"]


def test_paths_must_be_absolute() -> None:
    with pytest.raises(FfmpegError, match="absolute"):
        remux_args(FF, Path("-i/../x"), Path("/s/y"), OPUS)
    with pytest.raises(FfmpegError, match="absolute"):
        probe_args(FF, Path("concat:a|b"))


def test_loudness_of_one_file_and_of_an_album() -> None:
    one = loudness_args(FF, [Path("/m/a.opus")])
    assert one[one.index("-filter_complex") + 1] == "[0:a:0]ebur128=peak=true:framelog=quiet[out]"
    album = loudness_args(FF, [Path("/m/a.opus"), Path("/m/b.m4a")])
    graph = album[album.index("-filter_complex") + 1]
    assert "[a0][a1]concat=n=2:v=0:a=1,ebur128=peak=true" in graph
    assert album.count("-i") == 2
    with pytest.raises(FfmpegError):
        loudness_args(FF, [])


def test_parse_probe() -> None:
    body = {
        "streams": [{"codec_name": "opus", "sample_rate": "48000", "channels": 2}],
        "format": {"duration": "262.04", "bit_rate": "131072"},
    }
    probe = parse_probe(json.dumps(body).encode())
    assert probe == Probe("opus", 262040, 48000, 2, 131)
    assert probe.kind() == OPUS
    bare = parse_probe(b'{"streams": [{"codec_name": "flac", "duration": "nan"}]}')
    assert bare == Probe("flac", None, None, None, None)
    assert bare.kind() is None
    odd = parse_probe(b'{"streams": [{"duration": "1.5", "bit_rate": "x"}], "format": null}')
    assert (odd.codec, odd.duration_ms, odd.bit_rate_kbps) == ("", 1500, None)


@pytest.mark.parametrize("stdout", [b"", b"{}", b'{"streams": []}', b"[1]", b"not json"])
def test_parse_probe_without_audio(stdout: bytes) -> None:
    with pytest.raises(FfmpegError, match="no audio"):
        parse_probe(stdout)


def test_parse_loudness_takes_the_summary() -> None:
    loud = parse_loudness(b"[x] t: 0.1 I: -30.0 LUFS\n" + ebur128("-21.8", "-19.9"))
    assert loud == Loudness(-21.8, 0.101158)
    assert loud.gain_db == 3.8
    silent = parse_loudness(ebur128("-70.0", "-inf"))
    assert (silent.gain_db, silent.true_peak) == (0.0, 0.0)
    assert parse_loudness(ebur128("nan", "x")).true_peak == 0.0
    assert Loudness(-80.0, 0.1).gain_db == 0.0
    assert Loudness(-69.0, 0.1).gain_db == 51.0
    assert Loudness(60.0, 1.0).gain_db == -51.0
    with pytest.raises(FfmpegError, match="summary"):
        parse_loudness(b"nothing here")


async def test_the_wrapper_runs_the_tools_and_reports_failures(tmp_path: Path) -> None:
    runner = FakeRunner(lufs="-14.0", peak="0.0")
    ffmpeg = Ffmpeg(TaggingSettings(), runner)
    probe = await ffmpeg.probe(Path("/s/archive.opus"))
    assert probe.codec == "opus"
    assert runner.calls[0][0] == "/usr/bin/ffprobe"
    loud = await ffmpeg.loudness([Path("/s/archive.opus")])
    assert (loud.gain_db, loud.true_peak) == (-4.0, 1.0)
    target = tmp_path / "archive.opus"
    await ffmpeg.remux(Path("/s/a.webm"), target, OPUS)
    assert target.read_bytes() == (FIXTURES / "tone.opus").read_bytes()
    with pytest.raises(FfmpegError, match="already exists"):
        await ffmpeg.remux(Path("/s/a.webm"), target, OPUS)
    runner.fail = "ffmpeg"
    with pytest.raises(FfmpegError, match="ffmpeg exited 1: boom"):
        await ffmpeg.remux(Path("/s/a.webm"), tmp_path / "other.opus", OPUS)
    runner.fail = None
    with pytest.raises(FfmpegError, match="no archive"):
        await Ffmpeg(TaggingSettings(), _noop).remux(
            Path("/s/a.webm"), tmp_path / "none.opus", OPUS
        )


async def test_run_process_uses_argument_lists_and_a_timeout(tmp_path: Path) -> None:
    true, sleep = shutil.which("true"), shutil.which("sleep")
    assert true is not None
    assert sleep is not None
    done = await run_process([true], 5)
    assert done.returncode == 0
    with pytest.raises(FfmpegError, match="timed out"):
        await run_process([sleep, "5"], 0.05)
    with pytest.raises(FfmpegError, match="could not start"):
        await run_process([str(tmp_path / "missing-ffmpeg")], 5)


async def _noop(args: Sequence[str], timeout_s: float) -> ProcessResult:
    return ProcessResult(0, b"", b"")


# ---------------------------------------------------------------- golden runs (real ffmpeg)


def _stream_hash(path: Path) -> str:
    out = subprocess.run(  # noqa: S603 - argument list, test tool
        [
            real_settings().ffmpeg_path,
            "-nostdin",
            "-loglevel",
            "error",
            "-i",
            f"file:{path}",
            "-map",
            "0:a",
            "-c",
            "copy",
            "-f",
            "streamhash",
            "-hash",
            "sha256",
            "-",
        ],
        check=True,
        capture_output=True,
    )
    return out.stdout.decode().strip()


@needs_ffmpeg
@pytest.mark.parametrize(
    ("source", "kind", "codec"), [("tone.webm", OPUS, "opus"), ("tone.m4a", M4A, "aac")]
)
async def test_remux_never_transcodes(
    tmp_path: Path, source: str, kind: ArchiveKind, codec: str
) -> None:
    ffmpeg = Ffmpeg(real_settings())
    src = copy_fixture(source, tmp_path / source)
    assert (await ffmpeg.probe(src)).codec == codec
    dst = tmp_path / f"archive.{kind.ext}"
    await ffmpeg.remux(src, dst, kind)
    assert _stream_hash(dst) == _stream_hash(src)
    probe = await ffmpeg.probe(dst)
    assert probe.kind() == kind
    assert probe.duration_ms is not None
    assert abs(probe.duration_ms - 1000) < 50
    if kind == M4A:
        data = dst.read_bytes()
        assert data.index(b"moov") < data.index(b"mdat")  # faststart
    with pytest.raises(FfmpegError):  # never overwrites
        await ffmpeg.remux(src, dst, kind)


@needs_ffmpeg
async def test_track_and_album_loudness_of_the_tones() -> None:
    ffmpeg = Ffmpeg(real_settings())
    opus, m4a = FIXTURES / "tone.opus", FIXTURES / "tone-faststart.m4a"
    track = await ffmpeg.loudness([opus])
    assert -23.0 < track.integrated_lufs < -20.0
    assert math.isclose(track.gain_db, -18.0 - track.integrated_lufs, abs_tol=0.01)
    assert 0.05 < track.true_peak < 0.2
    album = await ffmpeg.loudness([opus, m4a])
    assert -23.0 < album.integrated_lufs < -20.0
    assert album.true_peak >= track.true_peak - 0.01


WHITELISTS = [
    "-format_whitelist",
    "matroska,ogg,mov",
    "-codec_whitelist",
    "opus,aac,vorbis,mp3float,mp3,flac",
    "-protocol_whitelist",
    "file",
]


def test_inputs_are_local_files_only() -> None:
    for args in (
        remux_args(FF, Path("/s/a.webm"), Path("/s/archive.opus"), OPUS),
        loudness_args(FF, [Path("/m/a.opus"), Path("/m/b.m4a")]),
    ):
        inputs = [i for i, arg in enumerate(args) if arg == "-i"]
        assert inputs
        for i in inputs:
            assert args[i - 6 : i] == WHITELISTS
    probe = probe_args(FF, Path("/s/a.opus"))
    assert probe[-9:] == ["-f", "ogg", *WHITELISTS, "file:/s/a.opus"]


@pytest.mark.parametrize(
    ("name", "demuxer"),
    [
        ("a.webm", "matroska"),
        ("a.WEBM", "matroska"),
        ("a.opus", "ogg"),
        ("a.ogg", "ogg"),
        ("a.m4a", "mov"),
        ("a.mp4", "mov"),
    ],
)
def test_the_input_demuxer_is_forced_from_the_extension(name: str, demuxer: str) -> None:
    """Audit L3: ffmpeg never guesses an input format from the content."""
    for args in (
        probe_args(FF, Path("/s") / name),
        remux_args(FF, Path("/s") / name, Path("/s/archive.opus"), OPUS),
        loudness_args(FF, [Path("/s") / name]),
    ):
        assert args[args.index("-f") + 1] == demuxer
        assert args.index("-f") < args.index(f"file:/s/{name}")


@pytest.mark.parametrize("name", ["a", "a.mp3", "a.flac", "a.txt", "a.m3u8", "a.webm.part"])
def test_inputs_of_unexpected_types_are_refused(name: str) -> None:
    path = Path("/s") / name
    with pytest.raises(FfmpegError, match="unexpected input type"):
        probe_args(FF, path)
    with pytest.raises(FfmpegError, match="unexpected input type"):
        remux_args(FF, path, Path("/s/archive.opus"), OPUS)
    with pytest.raises(FfmpegError, match="unexpected input type"):
        loudness_args(FF, [Path("/s/a.opus"), path])


@needs_ffmpeg
async def test_the_codec_whitelist_refuses_other_decoders(tmp_path: Path) -> None:
    """A file whose audio is not one of the expected codecs is not decoded at all."""
    src = tmp_path / "pcm.m4a"
    await anyio.run_process(
        [
            real_settings().ffmpeg_path,
            "-nostdin",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:a",
            "alac",
            f"file:{src}",
        ],
    )
    with pytest.raises(FfmpegError):
        await Ffmpeg(real_settings()).loudness([src])


@needs_ffmpeg
async def test_the_vorbis_webm_is_still_probed(tmp_path: Path) -> None:
    probe = await Ffmpeg(real_settings()).probe(copy_fixture("vorbis.webm", tmp_path / "v.webm"))
    assert probe.codec == "vorbis"
    assert probe.kind() is None
