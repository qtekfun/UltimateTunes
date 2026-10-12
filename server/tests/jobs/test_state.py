# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The job state machine: every allowed and refused move, failures, backoff, stream resets."""

import itertools

import pytest

from ultimatetunes.errors import InvalidStateTransition, WorkerErrorCode
from ultimatetunes.jobs import state as sm
from ultimatetunes.jobs.state import JobState

ALLOWED = {
    ("queued", "downloading"),
    ("queued", "cancelled"),
    ("downloading", "downloading"),
    ("downloading", "tagging"),
    ("downloading", "queued"),
    ("downloading", "failed"),
    ("downloading", "cancelled"),
    ("tagging", "tagging"),
    ("tagging", "ready"),
    ("tagging", "queued"),
    ("tagging", "failed"),
    ("tagging", "cancelled"),
    ("failed", "queued"),
    ("cancelled", "queued"),
}


@pytest.mark.parametrize(("src", "dst"), list(itertools.product(list(JobState), repeat=2)))
def test_every_pair_of_states(src: JobState, dst: JobState) -> None:
    if (src.value, dst.value) in ALLOWED:
        assert sm.check_transition(src, dst) == dst
    else:
        with pytest.raises(InvalidStateTransition):
            sm.check_transition(src, dst)


def test_ready_is_final_and_unknown_states_are_refused() -> None:
    assert sm.TRANSITIONS[JobState.READY] == frozenset()
    with pytest.raises(InvalidStateTransition, match="Unknown"):
        sm.check_transition("paused", "queued")
    with pytest.raises(InvalidStateTransition, match="Unknown"):
        sm.check_transition("queued", "paused")


def test_reports_only_move_forward() -> None:
    assert sm.check_report("downloading", "downloading") == JobState.DOWNLOADING
    assert sm.check_report("downloading", "tagging") == JobState.TAGGING
    assert sm.check_report("tagging", "tagging") == JobState.TAGGING
    with pytest.raises(InvalidStateTransition):
        sm.check_report("tagging", "downloading")
    for reported in ("ready", "queued", "failed", "cancelled"):
        with pytest.raises(InvalidStateTransition, match="cannot report"):
            sm.check_report("downloading", reported)


@pytest.mark.parametrize(
    ("attempt", "rand", "expected"),
    [
        (1, 0.5, 30.0),
        (2, 0.5, 120.0),
        (3, 0.5, 480.0),
        (7, 0.5, 480.0),
        (0, 0.5, 30.0),
        (1, 0.0, 24.0),
        (3, 0.0, 384.0),
        (2, 0.999999, 144.0),
    ],
)
def test_backoff_is_exponential_with_twenty_percent_jitter(
    attempt: int, rand: float, expected: float
) -> None:
    assert sm.retry_delay_s(attempt, lambda: rand) == pytest.approx(expected, abs=0.01)


def test_retryable_combines_the_worker_view_and_the_code_rule() -> None:
    assert sm.is_retryable("network_error", True)
    assert not sm.is_retryable("network_error", False)
    assert not sm.is_retryable("video_unavailable", True)
    assert not sm.is_retryable("made_up_code", True)
    for code in WorkerErrorCode:
        assert sm.is_retryable(code.value, True) == code.retryable


@pytest.mark.parametrize(
    ("code", "retryable", "attempts", "cancel", "expected"),
    [
        ("network_error", True, 1, False, JobState.QUEUED),
        ("network_error", True, 2, False, JobState.QUEUED),
        ("network_error", True, 3, False, JobState.FAILED),
        ("network_error", False, 1, False, JobState.FAILED),
        ("format_unavailable", True, 1, False, JobState.FAILED),
        ("invalid_video_id", True, 1, False, JobState.FAILED),
        ("cancelled", False, 1, False, JobState.CANCELLED),
        ("network_error", True, 1, True, JobState.CANCELLED),
        ("internal_error", True, 2, False, JobState.QUEUED),
    ],
)
def test_where_a_failure_goes(
    code: str, retryable: bool, attempts: int, cancel: bool, expected: JobState
) -> None:
    outcome = sm.failure_outcome(
        code, worker_says_retryable=retryable, attempts=attempts, max_attempts=3, cancel=cancel
    )
    assert outcome == expected


def test_expected_size_and_format_are_fixed_once_reported() -> None:
    assert sm.check_expected_size(None, None) is None
    assert sm.check_expected_size(None, 10) == 10
    assert sm.check_expected_size(10, 10) == 10
    with pytest.raises(InvalidStateTransition):
        sm.check_expected_size(10, 11)
    with pytest.raises(InvalidStateTransition):
        sm.check_expected_size(10, None)
    assert sm.check_fixed("formatId", None, "251") == "251"
    assert sm.check_fixed("formatId", "251", "251") == "251"
    with pytest.raises(InvalidStateTransition):
        sm.check_fixed("formatId", "251", "140")


@pytest.mark.parametrize(
    ("previous_format", "previous_size", "format_id", "size", "changed"),
    [
        (None, None, "251", 100, False),
        ("251", 100, "251", 100, False),
        ("251", 100, "140", 100, True),
        ("251", 100, "251", 101, True),
        ("251", None, "251", 100, False),
        ("251", 100, "251", None, False),
    ],
)
def test_a_retry_changes_the_stream_only_with_other_bytes(
    previous_format: str | None,
    previous_size: int | None,
    format_id: str,
    size: int | None,
    changed: bool,
) -> None:
    assert sm.retry_changes_stream(previous_format, previous_size, format_id, size) is changed
