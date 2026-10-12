# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`YtDlpDownloader`: the yt-dlp zipapp as a subprocess (spike T03c, SPEC section 11).

- Always an **argument list** (never a shell), the video id checked against
  `^[A-Za-z0-9_-]{11}$` first and placed after `--` (ids may start with `-`).
- Original audio only: `251/bestaudio[acodec=opus][protocol=https]/140/bestaudio[ext=m4a]
  [protocol=https]` with `--fixup never` (a fixup would rewrite the file under a reader).
- yt-dlp writes `<id>.<ext>.part` sequentially and renames it to `<id>.<ext>` when done (same
  inode). Progress comes as one JSON line per report (`UTP ...`), the final file as `UTF ...`;
  every other line is a log line, and `ERROR:` lines classify a failure (`classify`).
- Player clients come from settings, with one fallback ladder step when extraction fails
  before any byte was reported. Deno is the only JS runtime, with no remote components.
- The subprocess gets a minimal environment (no secrets) and is killed when the job is
  cancelled, the lease is lost or the timeout runs out.
"""

import json
import logging
import re
import sys
from collections import deque
from collections.abc import AsyncIterable, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

# Pipe constants only; the process starts with anyio and an argument list (module doc).
from subprocess import DEVNULL, PIPE  # nosec B404
from typing import Protocol

import anyio
from anyio.abc import Process

from ultimatetunes.core.storage import StagingStore
from ultimatetunes.errors import WorkerErrorCode
from ultimatetunes.worker.downloader import (
    DownloadError,
    DownloadProgress,
    DownloadResult,
    ProgressCallback,
    check_video_id,
)
from ultimatetunes.worker.settings import WorkerSettings

log = logging.getLogger(__name__)

FORMAT_SELECTOR = (
    "251/bestaudio[acodec=opus][protocol=https]/140/bestaudio[ext=m4a][protocol=https]"
)
PROGRESS_PREFIX = "UTP "
RESULT_PREFIX = "UTF "
# One JSON object of the progress, a tab, one of the format (JSON never contains a raw tab).
PROGRESS_TEMPLATE = (
    "download:" + PROGRESS_PREFIX + "%(progress.{status,downloaded_bytes,total_bytes,"
    "tmpfilename,filename})j\t%(info.{format_id,ext,acodec,filesize})j"
)
RESULT_TEMPLATE = (
    "after_move:" + RESULT_PREFIX + "%(.{id,format_id,ext,acodec,abr,asr,filesize,duration,"
    "filepath})j"
)
# Containers we accept, their MIME type, and whether they play while they grow (T03a/T03c):
# WebM/Opus has its index up front. YouTube's DASH M4A is fragmented, but its layout is not
# confirmed by a real download yet (T03c, pending), so it is served only once finished.
CONTAINERS: dict[str, tuple[str, bool]] = {
    "webm": ("audio/webm", True),
    "m4a": ("audio/mp4", False),
}
MAX_LINE = 64 * 1024
KEEP_LOG_LINES = 40
EXIT_USAGE = 2
_URL = re.compile(r"https?://\S+")


class ZipappSource(Protocol):
    """Where the current yt-dlp zipapp is (`YtDlpRuntime`)."""

    def current_zipapp(self) -> Path: ...


def redact(line: str) -> str:
    """Log-safe text: googlevideo URLs carry the client IP and tokens, so no URL is logged."""
    return _URL.sub("<url>", line)[:500]


def build_args(  # noqa: PLR0913 - the inputs of one yt-dlp command line
    *,
    python: str,
    zipapp: Path,
    deno: Path,
    clients: str,
    out_dir: Path,
    video_id: str,
) -> list[str]:
    """The yt-dlp command line (spike T03c). `video_id` must already be checked."""
    return [
        python,
        "-I",
        "-S",
        str(zipapp),
        "--ignore-config",
        "--no-plugin-dirs",
        "--no-cache-dir",
        "--no-playlist",
        "--no-mtime",
        "--fixup",
        "never",
        "--no-remote-components",
        "--no-js-runtimes",
        "--js-runtimes",
        f"deno:{deno}",
        "--extractor-args",
        f"youtube:player_client={clients}",
        "--format",
        FORMAT_SELECTOR,
        "--retries",
        "3",
        "--socket-timeout",
        "20",
        "--throttled-rate",
        "100K",
        "--buffer-size",
        "64K",
        "--no-resize-buffer",
        "--progress",
        "--newline",
        "--progress-delta",
        "0.5",
        "--progress-template",
        PROGRESS_TEMPLATE,
        "--print",
        RESULT_TEMPLATE,
        "--paths",
        f"home:{out_dir}",
        "--paths",
        f"temp:{out_dir}",
        "--output",
        f"{video_id}.%(ext)s",
        "--",
        f"https://www.youtube.com/watch?v={video_id}",
    ]


def minimal_env(tmp: Path) -> dict[str, str]:
    """The subprocess environment: nothing inherited, so no secret can leak into it."""
    return {
        "HOME": str(tmp),
        "TMPDIR": str(tmp),
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "DENO_NO_UPDATE_CHECK": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


# ---------------------------------------------------------------- classification

_STORAGE = (
    "No space left on device",
    "[Errno 28]",
    "Permission denied",
    "[Errno 13]",
    "Read-only file system",
    "[Errno 30]",
)
_AGE_OR_GONE = (
    "Sign in to confirm your age",
    "Video unavailable",
    "Private video",
    "This video has been removed",
    "This video is not available",
    "not available in your country",
    "available to this channel's members",
    "members-only",
    "This live event will begin",
    "Premieres in",
    "is offline",
    "copyright claim",
    "account associated with this video has been terminated",
)
_BLOCKED = ("not a bot", "HTTP Error 429", "Too Many Requests")
_EXTRACTOR = (
    "Requested format is not available",
    "Unable to extract",
    "challenge solving failed",
    "Signature extraction failed",
    "nsig extraction failed",
    "Some formats may be missing",
    "PO Token",
    "Unsupported URL",
)
_NETWORK = (
    "HTTP Error 403",
    "HTTP Error 5",
    "timed out",
    "Connection reset",
    "Connection refused",
    "ContentTooShortError",
    "IncompleteRead",
    "Unable to download",
    "urlopen error",
    "The page needs to be reloaded",
    "Temporary failure in name resolution",
    "Network is unreachable",
    "giving up after",
)
_RULES: tuple[tuple[tuple[str, ...], WorkerErrorCode], ...] = (
    (_STORAGE, WorkerErrorCode.STORAGE_ERROR),
    (_AGE_OR_GONE, WorkerErrorCode.VIDEO_UNAVAILABLE),
    (_BLOCKED, WorkerErrorCode.RATE_LIMITED_UPSTREAM),
    (_EXTRACTOR, WorkerErrorCode.EXTRACTOR_ERROR),
    (_NETWORK, WorkerErrorCode.NETWORK_ERROR),
)


def classify(errors: list[str], returncode: int) -> DownloadError:
    """The worker error of a failed yt-dlp run (spike T03c, "Error classes"). The first
    matching rule over all `ERROR:` lines wins; exit code 2 is a usage error, our own bug."""
    message = redact(errors[-1]) if errors else f"yt-dlp exited with {returncode}"
    if returncode == EXIT_USAGE and not errors:
        return DownloadError(WorkerErrorCode.INTERNAL_ERROR, message, retryable=False)
    text = "\n".join(errors)
    for needles, code in _RULES:
        if any(needle in text for needle in needles):
            return DownloadError(code, message)
    if returncode == EXIT_USAGE:
        return DownloadError(WorkerErrorCode.INTERNAL_ERROR, message, retryable=False)
    return DownloadError(WorkerErrorCode.INTERNAL_ERROR, message)


# ---------------------------------------------------------------- output parsing


@dataclass(frozen=True)
class ProgressLine:
    status: str
    downloaded_bytes: int
    total_bytes: int | None
    tmpfilename: str | None
    filename: str | None
    format_id: str
    ext: str


@dataclass(frozen=True)
class ResultLine:
    format_id: str
    ext: str
    filepath: str
    duration_s: float | None


def _int(value: object) -> int | None:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def parse_progress(line: str) -> ProgressLine | None:
    """A `UTP` line, or None when it is not one (or is malformed)."""
    if not line.startswith(PROGRESS_PREFIX):
        return None
    progress_text, _, info_text = line[len(PROGRESS_PREFIX) :].partition("\t")
    try:
        progress = json.loads(progress_text)
        info = json.loads(info_text) if info_text else {}
    except json.JSONDecodeError:
        return None
    if not isinstance(progress, dict) or not isinstance(info, dict):
        return None
    total = _int(progress.get("total_bytes"))
    return ProgressLine(
        status=str(progress.get("status", "")),
        downloaded_bytes=_int(progress.get("downloaded_bytes")) or 0,
        total_bytes=total if total and total > 0 else None,
        tmpfilename=_str_or_none(progress.get("tmpfilename")),
        filename=_str_or_none(progress.get("filename")),
        format_id=str(info.get("format_id") or ""),
        ext=str(info.get("ext") or ""),
    )


def parse_result(line: str) -> ResultLine | None:
    """The `UTF` line, or None when it is not one (or is malformed)."""
    if not line.startswith(RESULT_PREFIX):
        return None
    try:
        data = json.loads(line[len(RESULT_PREFIX) :])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not data.get("filepath"):
        return None
    duration = data.get("duration")
    return ResultLine(
        format_id=str(data.get("format_id") or ""),
        ext=str(data.get("ext") or ""),
        filepath=str(data["filepath"]),
        duration_s=float(duration) if isinstance(duration, int | float) else None,
    )


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


async def iter_lines(stream: AsyncIterable[bytes]) -> AsyncIterable[str]:
    """Lines of a byte stream (UTF-8, replacement on errors), each capped at `MAX_LINE`."""
    buffer = b""
    async for chunk in stream:
        buffer += chunk
        while b"\n" in buffer:
            raw, buffer = buffer.split(b"\n", 1)
            yield raw[:MAX_LINE].decode("utf-8", "replace").rstrip("\r")
        if len(buffer) > MAX_LINE:
            buffer = buffer[-MAX_LINE:]
    if buffer:
        yield buffer[:MAX_LINE].decode("utf-8", "replace").rstrip("\r")


# ---------------------------------------------------------------- the downloader


@dataclass
class _Run:
    """What one yt-dlp run reported."""

    job_dir: str
    out_dir: Path
    on_progress: ProgressCallback
    expected_size: int | None = None
    part_path: str | None = None
    final_path: str | None = None
    format_id: str | None = None
    ext: str | None = None
    downloaded: int = 0
    reported: bool = False
    result: ResultLine | None = None
    errors: deque[str] = field(default_factory=lambda: deque(maxlen=KEEP_LOG_LINES))
    failure: Exception | None = None

    def relative(self, absolute: str) -> str:
        """The staging-relative path of a file yt-dlp wrote: directly inside `out_dir`."""
        path = Path(absolute)
        if path.parent != self.out_dir or not path.name:
            raise DownloadError(
                WorkerErrorCode.INTERNAL_ERROR,
                "yt-dlp wrote outside the job directory",
                retryable=False,
            )
        return str(PurePosixPath(self.job_dir) / path.name)


def _container(ext: str) -> tuple[str, bool]:
    found = CONTAINERS.get(ext)
    if found is None:
        raise DownloadError(WorkerErrorCode.FORMAT_UNAVAILABLE, f"unexpected container {ext!r}")
    return found


Runner = Callable[[list[str], dict[str, str]], Awaitable[Process]]


async def _open(args: list[str], env: dict[str, str]) -> Process:
    # An argument list, never a shell; the id was checked and comes after `--`.
    return await anyio.open_process(args, stdin=DEVNULL, stdout=PIPE, stderr=PIPE, env=env)


class YtDlpDownloader:
    def __init__(
        self,
        staging: StagingStore,
        settings: WorkerSettings,
        runtime: ZipappSource,
        *,
        python: str = sys.executable,
        runner: Runner = _open,
    ) -> None:
        self._staging = staging
        self._settings = settings
        self._runtime = runtime
        self._python = python
        self._runner = runner

    def ladder(self) -> list[str]:
        """Player clients to try, in order (settings; duplicates and empties dropped)."""
        steps = [self._settings.ytdlp_player_clients, self._settings.ytdlp_fallback_clients]
        return [s for i, s in enumerate(steps) if s and s not in steps[:i]]

    async def download(
        self, video_id: str, job_dir: str, on_progress: ProgressCallback
    ) -> DownloadResult:
        check_video_id(video_id)
        out_dir = self._staging.local_path(job_dir)
        steps = self.ladder()
        for index, clients in enumerate(steps[:-1]):
            run = _Run(job_dir=job_dir, out_dir=out_dir, on_progress=on_progress)
            try:
                return await self._attempt(video_id, clients, run)
            except DownloadError as error:
                if run.reported or error.code != WorkerErrorCode.EXTRACTOR_ERROR:
                    raise
                log.warning(
                    "yt-dlp: clients %s failed (%s), trying %s",
                    clients,
                    error.message,
                    steps[index + 1],
                )
        last = _Run(job_dir=job_dir, out_dir=out_dir, on_progress=on_progress)
        return await self._attempt(video_id, steps[-1], last)

    async def _attempt(self, video_id: str, clients: str, run: _Run) -> DownloadResult:
        try:
            run.out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise DownloadError(WorkerErrorCode.STORAGE_ERROR, exc.strerror or "mkdir") from exc
        zipapp = self._runtime.current_zipapp()
        if not zipapp.is_file():
            raise DownloadError(WorkerErrorCode.INTERNAL_ERROR, "the zipapp is not installed")
        args = build_args(
            python=self._python,
            zipapp=zipapp,
            deno=self._settings.deno_path,
            clients=clients,
            out_dir=run.out_dir,
            video_id=video_id,
        )
        process = await self._runner(args, minimal_env(run.out_dir))
        try:
            with anyio.fail_after(self._settings.ytdlp_timeout_s):
                async with anyio.create_task_group() as tg:
                    for stream in (process.stdout, process.stderr):
                        if stream is not None:
                            tg.start_soon(self._consume_safely, stream, run, tg.cancel_scope)
                if run.failure is not None:
                    raise run.failure
                returncode = await process.wait()
        except TimeoutError as exc:
            raise DownloadError(WorkerErrorCode.NETWORK_ERROR, "yt-dlp timed out") from exc
        finally:
            if process.returncode is None:
                with anyio.CancelScope(shield=True):
                    process.kill()
                    await process.wait()
        if returncode != 0:
            raise classify(list(run.errors), returncode)
        return await self._finish(run)

    async def _consume_safely(
        self, stream: AsyncIterable[bytes], run: _Run, scope: anyio.CancelScope
    ) -> None:
        """Reads one stream. The first failure (a bad line, or the progress callback refusing,
        e.g. a lost lease) stops both readers and is raised as is, not in an exception group."""
        try:
            await self._consume(stream, run)
        except Exception as exc:  # noqa: BLE001 - re-raised by _attempt, unwrapped
            run.failure = run.failure or exc
            scope.cancel()

    async def _consume(self, stream: AsyncIterable[bytes], run: _Run) -> None:
        async for line in iter_lines(stream):
            progress = parse_progress(line)
            if progress is not None:
                await self._on_progress_line(progress, run)
                continue
            result = parse_result(line)
            if result is not None:
                run.result = result
            elif line.startswith("ERROR:"):
                run.errors.append(line)
                log.info("yt-dlp: %s", redact(line))
            elif line:
                log.debug("yt-dlp: %s", redact(line))

    async def _on_progress_line(self, line: ProgressLine, run: _Run) -> None:
        if line.status != "downloading" or not line.filename:
            return
        content_type, progressive = _container(line.ext)
        if run.final_path is None:
            run.final_path = run.relative(line.filename)
            run.part_path = run.relative(line.tmpfilename or f"{line.filename}.part")
            run.format_id = line.format_id or "unknown"
            run.ext = line.ext
        if run.expected_size is None:
            run.expected_size = line.total_bytes
        run.downloaded = max(run.downloaded, line.downloaded_bytes)
        run.reported = True
        await run.on_progress(
            DownloadProgress(
                downloaded_bytes=run.downloaded,
                expected_size=run.expected_size,
                part_path=run.part_path or run.final_path,
                final_path=run.final_path,
                finished=False,
                format_id=run.format_id or "unknown",
                content_type=content_type,
                progressive=progressive,
            )
        )

    async def _finish(self, run: _Run) -> DownloadResult:
        result = run.result
        if result is None:
            raise DownloadError(WorkerErrorCode.INTERNAL_ERROR, "yt-dlp reported no file")
        content_type, progressive = _container(result.ext)
        final = run.relative(result.filepath)
        if run.final_path is not None and final != run.final_path:
            raise DownloadError(WorkerErrorCode.INTERNAL_ERROR, "yt-dlp renamed the file")
        try:
            size = self._staging.size(final)
        except OSError as exc:
            raise DownloadError(WorkerErrorCode.STORAGE_ERROR, "downloaded file missing") from exc
        format_id = run.format_id or result.format_id or "unknown"
        await run.on_progress(
            DownloadProgress(
                downloaded_bytes=size,
                expected_size=run.expected_size,
                part_path=run.part_path or f"{final}.part",
                final_path=final,
                finished=True,
                format_id=format_id,
                content_type=content_type,
                progressive=progressive,
            )
        )
        duration_ms = None if result.duration_s is None else round(result.duration_s * 1000)
        return DownloadResult(final, format_id, result.ext, content_type, size, duration_ms)
