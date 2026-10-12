# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The streaming-while-downloading state machine (100 % lines and branches, CLAUDE.md)."""

from dataclasses import replace

import pytest

from ultimatetunes.streaming.state import (
    KEEP,
    Abort,
    Archived,
    CleanupPlan,
    Cursor,
    Done,
    Fail,
    Follow,
    JobView,
    Read,
    Start,
    Wait,
    cleanup_plan,
    plan_start,
    step,
)

PART = "job/1/Rb8Tn3ZcYv0.webm.part"
FINAL = "job/1/Rb8Tn3ZcYv0.webm"
PART2 = "job/2/Rb8Tn3ZcYv0.webm.part"
FINAL2 = "job/2/Rb8Tn3ZcYv0.webm"

# The first report of attempt 1: 100 of 1000 bytes of a front-indexed WebM.
GROWING = JobView(
    state="downloading",
    attempt_seq=1,
    bytes_downloaded=100,
    expected_size=1000,
    part_path=PART,
    final_path=FINAL,
    finished=False,
    format_id="251",
    content_type="audio/webm",
    progressive=True,
)
FINISHED = replace(GROWING, state="tagging", bytes_downloaded=1000, finished=True)
WHOLE = Cursor(attempt_seq=1, format_id="251", size=1000, offset=0, end=1000)
CHUNKED = Cursor(attempt_seq=1, format_id="251", size=None, offset=0, end=None)


# ------------------------------------------------------------------ JobView


def test_final_size_is_the_announced_size_or_the_complete_size() -> None:
    assert GROWING.final_size == 1000
    unknown = replace(GROWING, expected_size=None)
    assert unknown.final_size is None
    assert replace(unknown, finished=True).final_size == 100
    assert replace(unknown, state="ready").final_size == 100


def test_complete_once_finished_or_archived() -> None:
    assert not GROWING.complete
    assert FINISHED.complete
    assert replace(GROWING, state="ready").complete


# ------------------------------------------------------------------ plan_start


@pytest.mark.parametrize("state", ["failed", "cancelled"])
def test_a_failed_job_fails_the_request(state: str) -> None:
    assert plan_start(replace(GROWING, state=state)) == Fail()


def test_a_vanished_job_fails_the_request() -> None:
    assert plan_start(None) == Fail()


def test_an_archived_job_is_served_from_the_library() -> None:
    assert plan_start(replace(FINISHED, state="ready")) == Archived()


def test_a_queued_job_waits() -> None:
    assert plan_start(JobView(state="queued", attempt_seq=0)) == Wait()
    # Also a job waiting for its retry, with the failed attempt's report still on the row.
    assert plan_start(replace(GROWING, state="queued")) == Wait()


def test_a_claimed_job_waits_for_its_first_report() -> None:
    assert plan_start(JobView(state="downloading", attempt_seq=1)) == Wait()
    assert plan_start(replace(GROWING, format_id=None)) == Wait()
    assert plan_start(replace(GROWING, final_path=None)) == Wait()
    assert plan_start(replace(GROWING, part_path=None)) == Wait()


def test_it_waits_for_the_first_byte() -> None:
    assert plan_start(replace(GROWING, bytes_downloaded=0)) == Wait()


def test_an_end_indexed_format_waits_until_finished() -> None:
    late = replace(GROWING, progressive=False, format_id="140", content_type="audio/mp4")
    assert plan_start(late) == Wait()
    done = replace(late, bytes_downloaded=1000, finished=True)
    assert plan_start(done) == Start(1, 1000, "140", "audio/mp4", FINAL)


def test_known_size_starts_with_it() -> None:
    assert plan_start(GROWING) == Start(1, 1000, "251", "audio/webm", FINAL)
    assert plan_start(FINISHED) == Start(1, 1000, "251", "audio/webm", FINAL)


def test_unknown_size_starts_chunked_until_finished() -> None:
    unknown = replace(GROWING, expected_size=None)
    assert plan_start(unknown) == Start(1, None, "251", "audio/webm", FINAL)
    done = replace(unknown, bytes_downloaded=900, finished=True)
    assert plan_start(done) == Start(1, 900, "251", "audio/webm", FINAL)


def test_a_finished_file_of_the_wrong_size_is_not_served() -> None:
    assert plan_start(replace(FINISHED, bytes_downloaded=999)) == Wait()


def test_an_unknown_content_type_is_generic() -> None:
    plan = plan_start(replace(GROWING, content_type=None))
    assert isinstance(plan, Start)
    assert plan.content_type == "application/octet-stream"


# ------------------------------------------------------------------ step


def test_reads_what_the_worker_reported() -> None:
    assert step(WHOLE, GROWING) == Read((PART, FINAL), 0, 100)
    assert step(WHOLE.advanced(40), GROWING) == Read((PART, FINAL), 40, 60)


def test_waits_once_everything_reported_was_sent() -> None:
    assert step(WHOLE.advanced(100), GROWING) == Wait()


def test_reads_the_final_path_once_finished() -> None:
    assert step(WHOLE.advanced(100), FINISHED) == Read((FINAL, PART), 100, 900)


def test_a_range_stops_at_its_end() -> None:
    ranged = replace(WHOLE, offset=50, end=80)
    assert step(ranged, GROWING) == Read((PART, FINAL), 50, 30)
    assert step(replace(ranged, offset=80), GROWING) == Done()


def test_a_range_ahead_of_the_writer_waits() -> None:
    ahead = replace(WHOLE, offset=500, end=1000)
    assert step(ahead, GROWING) == Wait()
    assert step(ahead, replace(GROWING, bytes_downloaded=600)) == Read((PART, FINAL), 500, 100)


def test_done_after_the_whole_file() -> None:
    assert step(WHOLE.advanced(1000), FINISHED) == Done()


def test_chunked_ends_when_the_download_finishes() -> None:
    unknown = replace(GROWING, expected_size=None)
    assert step(CHUNKED, unknown) == Read((PART, FINAL), 0, 100)
    assert step(CHUNKED.advanced(100), unknown) == Wait()
    done = replace(unknown, bytes_downloaded=300, finished=True)
    assert step(CHUNKED.advanced(100), done) == Read((FINAL, PART), 100, 200)
    assert step(CHUNKED.advanced(300), done) == Done()


def test_a_listener_finishes_reading_after_the_archive() -> None:
    archived = replace(FINISHED, state="ready")
    assert step(WHOLE.advanced(600), archived) == Read((FINAL, PART), 600, 400)
    assert step(WHOLE.advanced(1000), archived) == Done()


def test_only_known_paths_are_read() -> None:
    assert step(WHOLE, replace(GROWING, final_path=None)) == Read((PART,), 0, 100)


@pytest.mark.parametrize("state", ["failed", "cancelled"])
def test_a_failed_job_aborts(state: str) -> None:
    assert step(WHOLE.advanced(10), replace(GROWING, state=state)) == Abort("the download failed")


def test_a_vanished_job_aborts() -> None:
    assert step(WHOLE, None) == Abort("the download failed")


def test_a_final_size_other_than_announced_aborts() -> None:
    short = replace(FINISHED, bytes_downloaded=990)
    assert step(WHOLE.advanced(100), short) == Abort(
        "the final size differs from the announced one"
    )


def test_a_retry_is_waited_for() -> None:
    assert step(WHOLE.advanced(100), replace(GROWING, state="queued")) == Wait()


def test_a_retry_with_the_same_bytes_is_followed() -> None:
    retry = replace(GROWING, attempt_seq=2, bytes_downloaded=0, part_path=PART2, final_path=FINAL2)
    moved = step(WHOLE.advanced(100), retry)
    assert moved == Follow(replace(WHOLE, attempt_seq=2, offset=100))
    assert isinstance(moved, Follow)
    # Then it waits for the new attempt to reach its offset, and reads on from its file.
    assert step(moved.cursor, retry) == Wait()
    assert step(moved.cursor, replace(retry, bytes_downloaded=150)) == Read(
        (PART2, FINAL2), 100, 50
    )


def test_a_retry_waits_for_its_first_report() -> None:
    claimed = JobView(state="downloading", attempt_seq=2)
    assert step(WHOLE.advanced(100), claimed) == Wait()


def test_a_retry_with_another_format_aborts() -> None:
    retry = replace(GROWING, attempt_seq=2, format_id="140")
    assert step(WHOLE, retry) == Abort("the retry downloads another format")
    assert step(CHUNKED, retry) == Abort("the retry downloads another format")


def test_a_retry_with_another_size_aborts() -> None:
    retry = replace(GROWING, attempt_seq=2, expected_size=1200)
    assert step(WHOLE, retry) == Abort("the retry downloads another size")


def test_a_retry_of_unknown_size_waits_for_its_size() -> None:
    retry = replace(GROWING, attempt_seq=2, expected_size=None)
    assert step(WHOLE, retry) == Wait()
    assert step(WHOLE, replace(retry, bytes_downloaded=1000, finished=True)) == Follow(
        replace(WHOLE, attempt_seq=2)
    )
    assert step(WHOLE, replace(retry, bytes_downloaded=999, finished=True)) == Abort(
        "the retry downloads another size"
    )


def test_a_chunked_listener_follows_any_retry_of_the_same_format() -> None:
    retry = replace(GROWING, attempt_seq=2, expected_size=None)
    assert step(CHUNKED, retry) == Follow(replace(CHUNKED, attempt_seq=2))


# ------------------------------------------------------------------ cleanup


def test_nothing_is_cleaned_while_someone_listens() -> None:
    assert cleanup_plan(replace(FINISHED, state="ready"), 1) == KEEP
    assert not KEEP.covers(1)


def test_an_archived_or_vanished_job_loses_its_whole_directory() -> None:
    assert cleanup_plan(replace(FINISHED, state="ready"), 0) == CleanupPlan(whole=True)
    assert cleanup_plan(None, 0) == CleanupPlan(whole=True)
    assert CleanupPlan(whole=True).covers(7)


def test_a_leased_attempt_keeps_its_directory() -> None:
    plan = cleanup_plan(replace(GROWING, attempt_seq=3), 0)
    assert plan == CleanupPlan(upto=2)
    assert plan.covers(1)
    assert plan.covers(2)
    assert not plan.covers(3)
    assert not plan.covers(0)


@pytest.mark.parametrize("state", ["queued", "failed", "cancelled"])
def test_an_idle_job_loses_its_attempt_directories(state: str) -> None:
    plan = cleanup_plan(replace(GROWING, state=state, attempt_seq=2), 0)
    assert plan == CleanupPlan(upto=2)
    assert plan.covers(2)
    assert not plan.covers(3)


def test_a_file_growing_past_the_announced_size_aborts() -> None:
    assert step(WHOLE.advanced(100), replace(GROWING, bytes_downloaded=1001)) == Abort(
        "the download grew past the announced size"
    )


def test_a_chunked_listener_past_the_end_of_a_retry_aborts() -> None:
    # It sent 500 bytes of attempt 1, followed attempt 2 (same format), which ends at 400.
    retry = replace(GROWING, attempt_seq=2, expected_size=None)
    moved = step(CHUNKED.advanced(500), retry)
    assert isinstance(moved, Follow)
    done = replace(retry, bytes_downloaded=400, finished=True)
    assert step(moved.cursor, done) == Abort("the listener passed the end of the final file")
    # Exactly at the end is a clean end.
    assert step(replace(moved.cursor, offset=400), done) == Done()
