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
- Abuse limits (core/limits.py): `--match-filter "duration<=N"` (`UT_MAX_TRACK_DURATION_S`;
  an unknown duration, e.g. a live stream, does not pass) and `--max-filesize`
  (`UT_MAX_DOWNLOAD_BYTES`). yt-dlp skips such a video with exit 0 and no file, saying so only
  on its screen output, so `--no-quiet` keeps that output on (`--print` would silence it):
  a skip it reports (`SKIP_MARKERS`) is `video_unavailable`, not retried; exit 0 without a file
  and without such a line stays a retryable `internal_error`. A download whose size is unknown
  up front and grows past the limit is stopped by the worker itself.
- The subprocess gets a minimal environment (no secrets) and is killed when the job is
  cancelled, the lease is lost or the timeout runs out.
- Optional PO token provider (D13): with `UT_YTDLP_POT_PROVIDER_URL` set, the only plugin
  directory is the image's pinned bgutil plugin (`--no-plugin-dirs --plugin-dirs <dir>`) and
  its HTTP provider gets the validated base URL. Unset, no plugin is loaded at all. PO tokens
  never reach a log (`redact`).
- Optional YouTube cookies (approved 2026-10-13): with `UT_YTDLP_COOKIES_FILE` set, yt-dlp
  authenticates a (throwaway) account to survive the "not a bot" wall. The configured path must
  live inside `/run/secrets` (the Docker secret mount), never built from metadata. yt-dlp
  rewrites the cookies file in place, so the read-only secret is never passed directly: it is
  copied to a private 0600 temp in the worker's tmpfs per attempt (`copy_cookies`), passed as
  `--cookies <copy>`, and deleted after the run, on success or failure. The cookie values live
  only in that file (never in the argument list), so they never reach a log.
"""

import json
import logging
import os
import re
import shutil
import sys
import tempfile
from collections import deque
from collections.abc import AsyncIterable, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

# Pipe constants only; the process starts with anyio and an argument list (module doc).
from subprocess import DEVNULL, PIPE  # nosec B404
from typing import Protocol

import anyio
from anyio.abc import Process

from ultimatetunes.core.limits import DownloadLimits
from ultimatetunes.core.storage import StagingStore
from ultimatetunes.errors import WorkerErrorCode
from ultimatetunes.worker.downloader import (
    DownloadError,
    DownloadProgress,
    DownloadResult,
    ProgressCallback,
    check_video_id,
)
from ultimatetunes.worker.settings import UNSAFE_URL_CHARS, WorkerSettings, internal_base_url

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
# What yt-dlp prints when a limit makes it skip the video (match filter, max-filesize).
SKIP_MARKERS = ("does not pass filter", "larger than max-filesize")
KEEP_LOG_LINES = 40
EXIT_USAGE = 2
_URL = re.compile(r"https?://\S+")
# A PO token next to its name ("POT: ...", "po_token=...", '"poToken": "..."').
_PO_TOKEN = re.compile(r"(?i)(po[ _-]?token|\bpot)([\"']?\s*[:=]\s*[\"']?)[A-Za-z0-9_\-+/=%.]{8,}")
# The bgutil plugin's HTTP provider (`youtubepot-bgutilhttp:base_url=...`).
POT_PROVIDER_ARGS = "youtubepot-bgutilhttp"
# The only directory a cookies file may live in: the Docker secret mount. It is never built
# from metadata and must never sit inside `/music` or `/staging`, so it can never be a file a
# download wrote. Tests inject their own roots through `YtDlpDownloader`.
ALLOWED_COOKIE_ROOTS: tuple[Path, ...] = (Path("/run/secrets"),)


class ZipappSource(Protocol):
    """Where the current yt-dlp zipapp is (`YtDlpRuntime`)."""

    def current_zipapp(self) -> Path: ...


def redact(line: str) -> str:
    """Log-safe text: googlevideo URLs carry the client IP and tokens, so no URL is logged, and
    a PO token printed by name is replaced too."""
    return _PO_TOKEN.sub(r"\1\2<redacted>", _URL.sub("<url>", line))[:500]


def build_args(  # noqa: PLR0913 - the inputs of one yt-dlp command line
    *,
    python: str,
    zipapp: Path,
    deno: Path,
    clients: str,
    out_dir: Path,
    video_id: str,
    limits: DownloadLimits,
    pot_provider_url: str | None = None,
    plugin_dir: Path | None = None,
    cookies_file: Path | None = None,
) -> list[str]:
    """The yt-dlp command line (spike T03c). `video_id` must already be checked. With
    `pot_provider_url` (D13), `plugin_dir` is the only plugin directory and the bgutil HTTP
    provider gets that base URL; without it no plugin is loaded. With `cookies_file`, yt-dlp
    gets `--cookies <path>` (a private copy, never the read-only secret; `copy_cookies`)."""
    # Validated integers only (pydantic checked them; `int` again so no text gets through).
    max_duration = int(limits.max_track_duration_s)
    max_bytes = int(limits.max_download_bytes)
    if max_duration <= 0 or max_bytes <= 0:
        raise ValueError("download limits must be positive")
    plugins = ["--no-plugin-dirs"]
    pot: list[str] = []
    if pot_provider_url is not None:
        # Settings validated it; checked again so nothing else can reach the argument.
        if (
            plugin_dir is None
            or internal_base_url(pot_provider_url) != pot_provider_url
            or UNSAFE_URL_CHARS & set(pot_provider_url)
        ):
            raise ValueError("the PO token provider needs a canonical URL and a plugin directory")
        plugins += ["--plugin-dirs", str(plugin_dir)]
        pot = ["--extractor-args", f"{POT_PROVIDER_ARGS}:base_url={pot_provider_url}"]
    cookies = ["--cookies", str(cookies_file)] if cookies_file is not None else []
    return [
        python,
        "-I",
        "-S",
        str(zipapp),
        "--ignore-config",
        "--no-quiet",
        *plugins,
        *cookies,
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
        *pot,
        "--format",
        FORMAT_SELECTOR,
        "--match-filter",
        f"duration<={max_duration}",
        "--max-filesize",
        str(max_bytes),
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


def cookies_source(configured: Path, allowed_roots: tuple[Path, ...]) -> Path:
    """The real cookies file to copy from, or a non-retryable error. The configured path must
    be absolute and sit inside one of `allowed_roots` (the Docker secret mount), both as given
    and after resolving symlinks, so it can never be redirected outside it, and it must be a
    regular file. The path is config, never user input, so a bad one is a misconfiguration."""
    roots = tuple(root.resolve() for root in allowed_roots)
    resolved = configured.resolve()

    def inside(path: Path) -> bool:
        return any(path == root or root in path.parents for root in roots)

    if not configured.is_absolute() or not inside(configured) or not inside(resolved):
        raise DownloadError(
            WorkerErrorCode.INTERNAL_ERROR,
            "the cookies file must be inside the allowed directory",
            retryable=False,
        )
    if not resolved.is_file():
        raise DownloadError(
            WorkerErrorCode.INTERNAL_ERROR,
            "the configured cookies file is missing",
            retryable=False,
        )
    return resolved


def copy_cookies(source: Path) -> Path:
    """A fresh 0600 copy of the cookies file in the worker's tmpfs (`/tmp`). yt-dlp refreshes
    the cookies file in place, so it must never get the read-only secret; it gets this private
    copy, which the caller deletes after the run. The content is a credential and is never
    logged. A failure cleans the half-written copy up before propagating."""
    fd, name = tempfile.mkstemp(prefix="ut-cookies-", suffix=".txt")
    copy = Path(name)
    try:
        copy.chmod(0o600)  # mkstemp already does this; make the intent explicit.
        with os.fdopen(fd, "wb") as dest, source.open("rb") as src:
            shutil.copyfileobj(src, dest)
    except BaseException:
        copy.unlink(missing_ok=True)
        raise
    return copy


def write_cookies(text: str) -> Path:
    """A fresh 0600 cookies file in the worker's tmpfs holding `text` (the session delivered
    with the job). yt-dlp refreshes it in place and the caller deletes it after the run; the
    content is a credential and is never logged. A failure cleans the file up first."""
    fd, name = tempfile.mkstemp(prefix="ut-cookies-", suffix=".txt")
    copy = Path(name)
    try:
        copy.chmod(0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as dest:
            dest.write(text)
    except BaseException:
        copy.unlink(missing_ok=True)
        raise
    return copy


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
# Failures that make `download` try the next client of the ladder (before any byte was served):
# a client that offers no usable format (extractor) or whose media URL is refused, e.g. a
# `403 Forbidden` on a SABR-only client (network).
_LADDER_RETRY: frozenset[WorkerErrorCode] = frozenset(
    {WorkerErrorCode.EXTRACTOR_ERROR, WorkerErrorCode.NETWORK_ERROR}
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
    skipped: str | None = None

    def relative(self, absolute: str) -> str:
        """The staging-relative path of a file yt-dlp wrote: directly inside `out_dir`."""
        path = Path(absolute)
        if path.parent != self.out_dir or path.name in ("", ".", ".."):
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
    def __init__(  # noqa: PLR0913 - its stores, settings and seams for tests
        self,
        staging: StagingStore,
        settings: WorkerSettings,
        runtime: ZipappSource,
        *,
        python: str = sys.executable,
        runner: Runner = _open,
        limits: DownloadLimits | None = None,
        cookies_roots: tuple[Path, ...] = ALLOWED_COOKIE_ROOTS,
    ) -> None:
        self._staging = staging
        self._settings = settings
        self._limits = limits or DownloadLimits()
        self._runtime = runtime
        self._python = python
        self._runner = runner
        self._cookies_roots = cookies_roots

    def ladder(self) -> list[str]:
        """Player clients to try, in order (settings; duplicates and empties dropped)."""
        steps = [self._settings.ytdlp_player_clients, self._settings.ytdlp_fallback_clients]
        return [s for i, s in enumerate(steps) if s and s not in steps[:i]]

    async def download(
        self,
        video_id: str,
        job_dir: str,
        on_progress: ProgressCallback,
        *,
        cookies: str | None = None,
    ) -> DownloadResult:
        check_video_id(video_id)
        out_dir = self._staging.local_path(job_dir)
        steps = self.ladder()
        for index, clients in enumerate(steps[:-1]):
            run = _Run(job_dir=job_dir, out_dir=out_dir, on_progress=on_progress)
            try:
                return await self._attempt(video_id, clients, run, cookies)
            except DownloadError as error:
                # Try the next client on an extraction failure (no downloadable format) or a
                # network failure such as a 403 on the media URL (a SABR-only client fails this
                # way), but only before any byte was served: once a listener is reading the
                # file, a different client would download other bytes under it, so the job fails
                # and a fresh attempt starts from scratch instead.
                if run.reported or error.code not in _LADDER_RETRY:
                    raise
                log.warning(
                    "yt-dlp: clients %s failed (%s), trying %s",
                    clients,
                    error.message,
                    steps[index + 1],
                )
        last = _Run(job_dir=job_dir, out_dir=out_dir, on_progress=on_progress)
        return await self._attempt(video_id, steps[-1], last, cookies)

    async def _attempt(
        self, video_id: str, clients: str, run: _Run, cookies: str | None = None
    ) -> DownloadResult:
        try:
            run.out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise DownloadError(WorkerErrorCode.STORAGE_ERROR, exc.strerror or "mkdir") from exc
        # Resolve `current` once: an update swapping the link mid-download never changes the
        # file this run executes.
        zipapp = self._runtime.current_zipapp().resolve()
        if not zipapp.is_file():
            raise DownloadError(WorkerErrorCode.INTERNAL_ERROR, "the zipapp is not installed")
        pot_url = self._settings.ytdlp_pot_provider_url
        plugin_dir = self._settings.ytdlp_plugin_dir
        if pot_url is not None and not plugin_dir.is_dir():
            # yt-dlp would refuse the directory; without the plugin, no PO token either.
            raise DownloadError(
                WorkerErrorCode.INTERNAL_ERROR, "the yt-dlp plugin directory is missing"
            )
        # yt-dlp rewrites the cookies file in place, so it never gets the read-only secret: a
        # private 0600 copy per attempt, deleted below whatever happens.
        cookies_copy = self._prepare_cookies(cookies)
        try:
            args = build_args(
                python=self._python,
                zipapp=zipapp,
                deno=self._settings.deno_path,
                clients=clients,
                out_dir=run.out_dir,
                video_id=video_id,
                limits=self._limits,
                pot_provider_url=pot_url,
                plugin_dir=plugin_dir,
                cookies_file=cookies_copy,
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
        finally:
            if cookies_copy is not None:
                cookies_copy.unlink(missing_ok=True)

    def _prepare_cookies(self, cookies: str | None) -> Path | None:
        """The per-attempt cookies copy to pass to yt-dlp, or None when no cookies are set.
        The admin/app session delivered with the job (decrypted by the api) wins; otherwise the
        optional `UT_YTDLP_COOKIES_FILE` fallback is used."""
        if cookies is not None:
            return write_cookies(cookies)
        configured = self._settings.ytdlp_cookies_file
        if configured is None:
            return None
        return copy_cookies(cookies_source(configured, self._cookies_roots))

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
            elif any(marker in line for marker in SKIP_MARKERS):
                run.skipped = redact(line)
                log.info("yt-dlp: %s", run.skipped)
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
        self._check_size(run)
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

    def _check_size(self, run: _Run) -> None:
        """Stops a download that is (or announces to be) over `UT_MAX_DOWNLOAD_BYTES`."""
        limit = self._limits.max_download_bytes
        if run.downloaded > limit or (run.expected_size or 0) > limit:
            raise DownloadError(
                WorkerErrorCode.VIDEO_UNAVAILABLE,
                f"the audio is larger than this server allows ({limit} bytes)",
                retryable=False,
            )

    async def _finish(self, run: _Run) -> DownloadResult:
        result = run.result
        if result is None and run.skipped is not None:
            raise DownloadError(
                WorkerErrorCode.VIDEO_UNAVAILABLE,
                "yt-dlp skipped the video: longer or larger than this server allows",
                retryable=False,
            )
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
        # Abort on a size mismatch (SPEC section 11): if the worker announced the exact size, a
        # final file of any other size is a truncated or corrupt download and must never be
        # handed to the archiver as complete. Retry it (another client or attempt); the stream
        # of this attempt is cut by the api (a failed job ends open streams).
        if run.expected_size is not None and size != run.expected_size:
            raise DownloadError(
                WorkerErrorCode.NETWORK_ERROR,
                f"the download ended at {size} bytes, not the announced {run.expected_size}",
            )
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
