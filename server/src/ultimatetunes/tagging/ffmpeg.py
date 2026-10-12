# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""ffmpeg and ffprobe: probe, remux (never transcode) and ReplayGain (SPEC section 11).

- Every call is an **argument list** (never a shell), with `-nostdin`, a minimal environment
  (no secret can leak into it) and a timeout. File arguments are absolute paths from the
  stores, passed as `file:<path>` so ffmpeg never reads them as another protocol or option.
- `remux`: stream copy of the first audio stream into the archive container: Opus to Ogg/Opus
  (`.opus`), AAC to MP4 with `+faststart` (`.m4a`). Source metadata and chapters are dropped
  (our tags are written afterwards), `+bitexact` keeps the output reproducible.
- `loudness`: EBU R128 integrated loudness and true peak over one file, or over a whole album
  (the files concatenated), with ffmpeg's `ebur128` filter. ReplayGain 2.0 gain is
  `-18 LUFS - integrated`; a file with no measurable loudness (silence) gets 0 dB.
"""

import json
import math
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from subprocess import DEVNULL  # nosec B404
from typing import Any

import anyio

from ultimatetunes.tagging.model import KIND_BY_CODEC, ArchiveKind
from ultimatetunes.tagging.settings import TaggingSettings

REFERENCE_LUFS = -18.0
# ebur128 reports -70 LUFS (its absolute gate) when nothing is loud enough to measure.
SILENCE_LUFS = -70.0
# The most a gain may change a file, both ways (absurd values mean a broken measurement).
MAX_GAIN_DB = 51.0
_ENV = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"}
_INTEGRATED = re.compile(r"^\s*I:\s+(\S+)\s+LUFS\s*$", re.MULTILINE)
_PEAK = re.compile(r"^\s*Peak:\s+(\S+)\s+dBFS\s*$", re.MULTILINE)
_KEEP_STDERR = 400


class FfmpegError(Exception):
    """ffmpeg/ffprobe failed, timed out, or answered something unexpected."""


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes


Runner = Callable[[Sequence[str], float], Awaitable[ProcessResult]]


async def run_process(args: Sequence[str], timeout_s: float) -> ProcessResult:
    """The real runner: argument list, no stdin, minimal environment, bounded in time."""
    try:
        with anyio.fail_after(timeout_s):
            done = await anyio.run_process(list(args), stdin=DEVNULL, check=False, env=_ENV)
    except TimeoutError as exc:
        raise FfmpegError(f"{Path(args[0]).name} timed out after {timeout_s:.0f} s") from exc
    except OSError as exc:
        raise FfmpegError(f"{Path(args[0]).name} could not start: {exc.strerror}") from exc
    return ProcessResult(done.returncode, done.stdout or b"", done.stderr or b"")


@dataclass(frozen=True)
class Probe:
    codec: str
    duration_ms: int | None
    sample_rate_hz: int | None
    channels: int | None
    bit_rate_kbps: int | None

    def kind(self) -> ArchiveKind | None:
        return KIND_BY_CODEC.get(self.codec)


@dataclass(frozen=True)
class Loudness:
    integrated_lufs: float
    true_peak: float

    @property
    def gain_db(self) -> float:
        if self.integrated_lufs <= SILENCE_LUFS:
            return 0.0
        gain = REFERENCE_LUFS - self.integrated_lufs
        return round(max(-MAX_GAIN_DB, min(MAX_GAIN_DB, gain)), 2)


def _file(path: Path) -> str:
    if not path.is_absolute():
        raise FfmpegError("ffmpeg needs absolute paths")
    return f"file:{path}"


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int(value: Any) -> int | None:
    number = _number(value)
    return None if number is None else int(number)


def _float_or(text: str, default: float) -> float:
    try:
        value = float(text)
    except ValueError:
        return default
    return value if math.isfinite(value) else default


def parse_probe(stdout: bytes) -> Probe:
    try:
        data = json.loads(stdout)
        stream = data["streams"][0]
        fmt = data.get("format") or {}
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise FfmpegError("ffprobe found no audio stream") from exc
    seconds = _number(stream.get("duration"))
    if seconds is None:
        seconds = _number(fmt.get("duration"))
    duration = None if seconds is None else round(seconds * 1000)
    bit_rate = _int(stream.get("bit_rate") or fmt.get("bit_rate"))
    return Probe(
        codec=str(stream.get("codec_name") or ""),
        duration_ms=duration,
        sample_rate_hz=_int(stream.get("sample_rate")),
        channels=_int(stream.get("channels")),
        bit_rate_kbps=round(bit_rate / 1000) if bit_rate else None,
    )


def parse_loudness(stderr: bytes) -> Loudness:
    text = stderr.decode("utf-8", errors="replace")
    integrated = _INTEGRATED.findall(text)
    peaks = _PEAK.findall(text)
    if not integrated or not peaks:
        raise FfmpegError("ebur128 printed no summary")
    lufs = _float_or(integrated[-1], SILENCE_LUFS)
    peak_db = _float_or(peaks[-1], -math.inf)
    peak = round(10 ** (peak_db / 20), 6) if math.isfinite(peak_db) else 0.0
    return Loudness(lufs, peak)


def loudness_args(ffmpeg: Path, paths: Sequence[Path]) -> list[str]:
    """One file, or several concatenated (album gain): all resampled to 48 kHz stereo float so
    `concat` accepts them; ebur128 measures the result."""
    if not paths:
        raise FfmpegError("loudness of nothing")
    args = [str(ffmpeg), "-nostdin", "-hide_banner", "-nostats", "-loglevel", "info"]
    for path in paths:
        args += ["-i", _file(path)]
    if len(paths) == 1:
        graph = "[0:a:0]ebur128=peak=true:framelog=quiet[out]"
    else:
        chains = [
            f"[{i}:a:0]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[a{i}]"
            for i in range(len(paths))
        ]
        inputs = "".join(f"[a{i}]" for i in range(len(paths)))
        measure = f"{inputs}concat=n={len(paths)}:v=0:a=1,ebur128=peak=true:framelog=quiet[out]"
        graph = ";".join([*chains, measure])
    return [*args, "-filter_complex", graph, "-map", "[out]", "-f", "null", "-"]


def remux_args(ffmpeg: Path, src: Path, dst: Path, kind: ArchiveKind) -> list[str]:
    return [
        str(ffmpeg),
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-n",
        "-i",
        _file(src),
        "-map",
        "0:a:0",
        "-c:a",
        "copy",
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-fflags",
        "+bitexact",
        *kind.muxer_args,
        "-f",
        kind.muxer,
        _file(dst),
    ]


def probe_args(ffprobe: Path, path: Path) -> list[str]:
    return [
        str(ffprobe),
        "-v",
        "error",
        "-of",
        "json",
        "-select_streams",
        "a:0",
        "-show_streams",
        "-show_format",
        _file(path),
    ]


class Ffmpeg:
    def __init__(self, settings: TaggingSettings, run: Runner = run_process) -> None:
        self._settings = settings
        self._run = run

    async def _call(self, args: Sequence[str]) -> ProcessResult:
        result = await self._run(args, self._settings.ffmpeg_timeout_s)
        if result.returncode != 0:
            tail = result.stderr.decode("utf-8", errors="replace").strip()[-_KEEP_STDERR:]
            raise FfmpegError(f"{Path(args[0]).name} exited {result.returncode}: {tail}")
        return result

    async def probe(self, path: Path) -> Probe:
        result = await self._call(probe_args(self._settings.ffprobe_path, path))
        return parse_probe(result.stdout)

    async def remux(self, src: Path, dst: Path, kind: ArchiveKind) -> None:
        # `-n` refuses to overwrite but still exits 0: check both sides here.
        target = anyio.Path(dst)
        if await target.exists():
            raise FfmpegError("the remux target already exists")
        await self._call(remux_args(self._settings.ffmpeg_path, src, dst, kind))
        if not await target.is_file() or (await target.stat()).st_size == 0:
            raise FfmpegError("ffmpeg wrote no archive file")

    async def loudness(self, paths: Sequence[Path]) -> Loudness:
        result = await self._call(loudness_args(self._settings.ffmpeg_path, paths))
        return parse_loudness(result.stderr)
