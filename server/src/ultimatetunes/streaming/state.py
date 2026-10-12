# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The streaming-while-downloading state machine (SPEC section 11, 100 % coverage, CLAUDE.md).

Pure decisions, no I/O. The service (`service.py`) feeds them the job as the worker last
reported it (`JobView`, from the job row) and does what they say.

Before the response starts, `plan_start` says what to answer:

    queued, or no servable bytes yet ──▶ Wait
    downloading/tagging with bytes ────▶ Start (exact size when known, else chunked)
    ready (archived) ──────────────────▶ Archived (serve the library file)
    failed / cancelled / gone ─────────▶ Fail (error 70, HTTP 404)

"Servable" means the worker reported a format and its paths, and either the download is
`finished`, or the format is `progressive` (index at the front) and at least one byte exists.

Once the headers are out, `step` moves one listener (`Cursor`) forward:

- `Read` the bytes the worker reported and this response still needs: from `partPath` while
  the download runs, from `finalPath` once it is `finished` (a reader that already holds the
  file keeps reading it: the rename keeps the inode);
- `Wait` for the next report when it has sent everything reported so far;
- `Done` once it has sent its whole range (or the whole file when chunked);
- `Abort` (cut the transfer without a clean end) when the job failed or is gone, when the size
  at `finished` differs from the announced one (or the file grows past it), when a retry
  downloads another format or another exact size, or when a chunked listener that followed a
  retry has already sent more bytes than the retry's final file holds;
- `Follow` a retry that downloads the same format and size: the bytes are the same, so the
  listener goes on from the new attempt's file at its offset.

`cleanup_plan` decides which staging directories (`<jobId>/<attemptSeq>`) can go: none while a
listener streams from the job, never the one a leased attempt is writing, every one once the
job is archived.
"""

from dataclasses import dataclass, replace
from typing import Final

QUEUED: Final = "queued"
READY: Final = "ready"
LEASED: Final = frozenset({"downloading", "tagging"})
ENDED: Final = frozenset({"failed", "cancelled"})


@dataclass(frozen=True)
class JobView:
    """What the api knows about the job's current attempt (the worker's last report)."""

    state: str
    attempt_seq: int
    bytes_downloaded: int = 0
    expected_size: int | None = None
    part_path: str | None = None
    final_path: str | None = None
    finished: bool = False
    format_id: str | None = None
    content_type: str | None = None
    progressive: bool = False

    @property
    def complete(self) -> bool:
        """The attempt's file is whole: `finished` reported, or the job is archived."""
        return self.finished or self.state == READY

    @property
    def final_size(self) -> int | None:
        """The exact size of the file: announced by the worker, or known once complete."""
        if self.expected_size is not None:
            return self.expected_size
        return self.bytes_downloaded if self.complete else None


# ------------------------------------------------------------------ before the response


@dataclass(frozen=True)
class Wait:
    """Nothing to do until the next report."""


@dataclass(frozen=True)
class Fail:
    """The download failed (or the job is gone): error 70 with HTTP 404."""


@dataclass(frozen=True)
class Archived:
    """The job is done: the song is a library file now."""


@dataclass(frozen=True)
class Start:
    """Answer now. `size` is exact, or None (chunked, Range ignored)."""

    attempt_seq: int
    size: int | None
    format_id: str
    content_type: str
    final_path: str


def _servable(view: JobView) -> bool:
    if view.part_path is None:
        return False
    if view.finished:
        # A file whose size is not the announced one is wrong: wait for the worker's verdict.
        return view.expected_size is None or view.expected_size == view.bytes_downloaded
    return view.progressive and view.bytes_downloaded > 0


def plan_start(view: JobView | None) -> Wait | Fail | Archived | Start:
    if view is None or view.state in ENDED:
        return Fail()
    if view.state == READY:
        return Archived()
    format_id, final_path = view.format_id, view.final_path
    if view.state not in LEASED or format_id is None or final_path is None:
        return Wait()
    if not _servable(view):
        return Wait()
    return Start(
        attempt_seq=view.attempt_seq,
        size=view.final_size,
        format_id=format_id,
        content_type=view.content_type or "application/octet-stream",
        final_path=final_path,
    )


# ------------------------------------------------------------------ while streaming


@dataclass(frozen=True)
class Cursor:
    """One listener: the attempt it reads, what it announced and how far it got."""

    attempt_seq: int
    format_id: str
    size: int | None  # announced exact size, None when chunked
    offset: int  # next byte to send (absolute in the file)
    end: int | None  # exclusive end of the response; None = until the download finishes

    def advanced(self, count: int) -> "Cursor":
        return replace(self, offset=self.offset + count)


@dataclass(frozen=True)
class Read:
    """Send up to `length` bytes from `offset` of the first of `paths` that exists."""

    paths: tuple[str, ...]
    offset: int
    length: int


@dataclass(frozen=True)
class Done:
    """The response is complete: end it cleanly."""


@dataclass(frozen=True)
class Abort:
    """Cut the transfer without a clean end (never pass a broken file off as complete)."""

    reason: str


@dataclass(frozen=True)
class Follow:
    """A retry with the same bytes: go on from the new attempt's file."""

    cursor: Cursor


def _follow(cursor: Cursor, view: JobView) -> Wait | Abort | Follow:
    """A new attempt of the job: continue only when it produces the same bytes."""
    if view.format_id is None:
        return Wait()
    if view.format_id != cursor.format_id:
        return Abort("the retry downloads another format")
    if cursor.size is not None:
        size = view.final_size
        if size is None:
            return Wait()
        if size != cursor.size:
            return Abort("the retry downloads another size")
    return Follow(replace(cursor, attempt_seq=view.attempt_seq))


def _broken(cursor: Cursor, view: JobView) -> Abort | None:
    """Bytes that cannot be the ones this listener announced or already sent."""
    if cursor.size is not None and view.bytes_downloaded > cursor.size:
        return Abort("the download grew past the announced size")
    if not view.complete:
        return None
    if cursor.size is not None and view.bytes_downloaded != cursor.size:
        return Abort("the final size differs from the announced one")
    if cursor.offset > view.bytes_downloaded:
        # A chunked listener that followed a retry and already sent more than its final file.
        return Abort("the listener passed the end of the final file")
    return None


def _read_on(cursor: Cursor, view: JobView) -> Read | Wait | Done | Abort:
    """The listener and the worker are on the same attempt."""
    broken = _broken(cursor, view)
    if broken is not None:
        return broken
    end = cursor.end
    if view.complete and end is None:
        end = view.bytes_downloaded
    if end is not None and cursor.offset >= end:
        return Done()
    available = view.bytes_downloaded if end is None else min(view.bytes_downloaded, end)
    if cursor.offset >= available:
        return Wait()
    first, second = view.part_path, view.final_path
    if view.complete:
        first, second = second, first
    paths = tuple(p for p in (first, second) if p is not None)
    return Read(paths, cursor.offset, available - cursor.offset)


def step(cursor: Cursor, view: JobView | None) -> Read | Wait | Done | Abort | Follow:
    if view is None or view.state in ENDED:
        return Abort("the download failed")
    if view.state == QUEUED:
        return Wait()  # a retry is coming
    if view.attempt_seq != cursor.attempt_seq:
        return _follow(cursor, view)
    return _read_on(cursor, view)


# ------------------------------------------------------------------ staging cleanup


@dataclass(frozen=True)
class CleanupPlan:
    """Delete the whole `<jobId>/` directory, or the attempt directories `1..upto`."""

    whole: bool = False
    upto: int = 0

    def covers(self, attempt_seq: int) -> bool:
        return self.whole or 1 <= attempt_seq <= self.upto


KEEP: Final = CleanupPlan()


def cleanup_plan(view: JobView | None, listeners: int) -> CleanupPlan:
    """Which staging directories of a job may be deleted now. A failed or cancelled job may be
    requested again (a new attempt directory appears), so only an archived or vanished job
    loses its whole directory."""
    if listeners > 0:
        return KEEP
    if view is None or view.state == READY:
        return CleanupPlan(whole=True)
    if view.state in LEASED:
        return CleanupPlan(upto=view.attempt_seq - 1)
    return CleanupPlan(upto=view.attempt_seq)
