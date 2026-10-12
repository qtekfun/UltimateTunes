# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A worker killed mid-download (SIGKILL, no goodbye) leaves a leased job; once the lease expires
the job goes back to the queue and the next worker run finishes it (SPEC section 3, leases)."""

import pytest

from tests.e2e.conftest import UserFactory
from tests.e2e.stack import Compose, wait_until

pytestmark = pytest.mark.e2e

VIDEO = "Wq5Jd7HsKe2"
SONG = f"yt:{VIDEO}"
TITLE = "Night Ferry"


def test_a_killed_worker_leaves_a_job_that_another_run_finishes(
    make_user: UserFactory, compose: Compose
) -> None:
    user = make_user("dave")
    requested = user.ut("POST", f"/tracks/{SONG}/request", json={"reason": "keep"})
    assert requested.status_code == 202, requested.text

    def mid_download() -> dict[str, object] | None:
        status = user.status(SONG)
        assert status["state"] != "ready", "the download finished before the worker was killed"
        return status if status["state"] == "downloading" and status["progress"] > 0 else None

    first = wait_until(mid_download, timeout_s=60.0, what="the download to start")
    assert first["attempts"] == 1
    try:
        compose.kill("worker")
        assert not compose.is_running("worker")
        # Nobody works on it now: the job stays as it was until its lease expires.
        stalled = user.status(SONG)
        assert stalled["state"] in ("downloading", "queued"), stalled
    finally:
        compose.start("worker")

    # The restarted worker claims the job once the lease expired (15 s on the e2e stack) and the
    # retry backoff passed, and completes it as a second attempt.
    ready = user.wait_ready(SONG, timeout_s=180.0)
    assert ready["attempts"] == 2
    song = user.rest("getSong", id=ready["trackId"])["song"]
    assert (song["title"], song["suffix"]) == (TITLE, "opus")
    with user.stream(ready["trackId"]) as answer:
        assert answer.status_code == 200
        assert len(answer.read()) == song["size"]
