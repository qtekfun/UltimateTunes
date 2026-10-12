# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The job state machine (contracts/openapi/internal-worker.yaml, 100 % coverage, CLAUDE.md).

Pure decisions, no I/O: the queue (`queue.py`) asks this module which move is allowed and
where a release goes, then writes the result with conditional updates.

    queued ──claim──▶ downloading ──progress──▶ tagging ──complete──▶ ready
      ▲  ▲                 │                       │
      │  └──retry/expiry───┴───────────────────────┤
      │                    └──fail / expiry────────┴──▶ failed | cancelled
      └──────────────── request again ◀────────────────── failed | cancelled

- A worker reports `downloading` (repeatable) and moves to `tagging` once; going back is not
  allowed. `complete` is only accepted from `tagging`.
- A failure goes back to `queued` with exponential backoff (30 s, 2 min, 8 min, ±20 % jitter)
  while attempts are left and the code is retryable (contracts/errors.md); otherwise it ends
  `failed`, or `cancelled` when an admin asked for it.
- `failed` and `cancelled` go back to `queued` only through a new request (attempts reset).
"""

from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Final

from ultimatetunes.errors import InvalidStateTransition, WorkerErrorCode


class JobState(StrEnum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    TAGGING = "tagging"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Every allowed move. Anything else is `InvalidStateTransition`.
TRANSITIONS: Final[Mapping[JobState, frozenset[JobState]]] = {
    JobState.QUEUED: frozenset({JobState.DOWNLOADING, JobState.CANCELLED}),
    JobState.DOWNLOADING: frozenset(
        {
            JobState.DOWNLOADING,
            JobState.TAGGING,
            JobState.QUEUED,
            JobState.FAILED,
            JobState.CANCELLED,
        }
    ),
    JobState.TAGGING: frozenset(
        {JobState.TAGGING, JobState.READY, JobState.QUEUED, JobState.FAILED, JobState.CANCELLED}
    ),
    JobState.READY: frozenset(),
    JobState.FAILED: frozenset({JobState.QUEUED}),
    JobState.CANCELLED: frozenset({JobState.QUEUED}),
}

# States that hold a lease.
LEASED: Final = frozenset({JobState.DOWNLOADING, JobState.TAGGING})
# States a worker may report in `progress`.
REPORTABLE: Final = frozenset({JobState.DOWNLOADING, JobState.TAGGING})

# Backoff of retryable failures (contracts/errors.md): 30 s, 2 min, 8 min, ±20 % jitter.
BACKOFF_BASE_S: Final = 30
BACKOFF_FACTOR: Final = 4
BACKOFF_STEPS: Final = 3
JITTER: Final = 0.2


def check_transition(current: str, target: str) -> JobState:
    """The target state when the move is allowed, else `InvalidStateTransition`."""
    try:
        src, dst = JobState(current), JobState(target)
    except ValueError as exc:
        raise InvalidStateTransition(f"Unknown job state in {current} -> {target}") from exc
    if dst not in TRANSITIONS[src]:
        raise InvalidStateTransition(f"A {src} job cannot become {dst}")
    return dst


def check_report(current: str, reported: str) -> JobState:
    """A `progress` report: only `downloading`/`tagging`, never backwards."""
    if reported not in REPORTABLE:
        raise InvalidStateTransition(f"A worker cannot report {reported}")
    return check_transition(current, reported)


def retry_delay_s(attempt: int, rand: Callable[[], float]) -> float:
    """Backoff before the next attempt after attempt number `attempt` failed (1-based).
    `rand` returns a float in [0, 1) and sets the jitter."""
    step = min(max(attempt, 1), BACKOFF_STEPS) - 1
    base = BACKOFF_BASE_S * BACKOFF_FACTOR**step
    return float(base * (1 - JITTER + 2 * JITTER * rand()))


def is_retryable(code: str, worker_says: bool) -> bool:
    """The worker's view, overruled by the per-code rule of contracts/errors.md."""
    try:
        known = WorkerErrorCode(code)
    except ValueError:
        return False
    return worker_says and known.retryable


def failure_outcome(
    code: str, *, worker_says_retryable: bool, attempts: int, max_attempts: int, cancel: bool
) -> JobState:
    """Where a `fail` sends a leased job: `cancelled` (admin cancel or `cancelled` code),
    `queued` (retryable with attempts left) or `failed`."""
    if cancel or code == WorkerErrorCode.CANCELLED:
        return JobState.CANCELLED
    if is_retryable(code, worker_says_retryable) and attempts < max_attempts:
        return JobState.QUEUED
    return JobState.FAILED


def check_expected_size(stored: int | None, reported: int | None) -> int | None:
    """`expectedSize` is set once per attempt and never changes (never an estimate)."""
    if stored is None:
        return reported
    if reported != stored:
        raise InvalidStateTransition("expectedSize cannot change within an attempt")
    return stored


def check_fixed(name: str, stored: str | None, reported: str) -> str:
    """Fields fixed by the first report of an attempt (`formatId`, `partPath`, `finalPath`):
    one attempt downloads one format into one file."""
    if stored is not None and stored != reported:
        raise InvalidStateTransition(f"{name} cannot change within an attempt")
    return reported


def retry_changes_stream(
    previous_format: str | None,
    previous_size: int | None,
    format_id: str,
    expected_size: int | None,
) -> bool:
    """True when a retry produces other bytes than the previous attempt, so open streams of
    the job must be aborted: another format, or another exact size when both are known. With
    no previous report there is nothing to compare (and no stream was open)."""
    if previous_format is None:
        return False
    if previous_format != format_id:
        return True
    both_known = previous_size is not None and expected_size is not None
    return both_known and previous_size != expected_size
