# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`StagingJanitor`: the api owns staging cleanup (contracts/openapi/internal-worker.yaml).

Each attempt writes to `<jobId>/<attemptSeq>/`. Once nobody streams from a job, the directories
it no longer needs go (`state.cleanup_plan`):

- `clean_job(job_id)`: right after the last listener of the job closes, and after the worker's
  `complete` or `fail` (the middleware of `web.py`);
- `sweep()`: every `UT_STAGING_SWEEP_INTERVAL_S`, for whatever the events missed (a restart,
  another replica, a job nobody listened to before it was re-queued).

The janitor reads the job before deleting, and a sweep lists the directories before reading the
jobs: a directory that exists was created by a claim that the job row already shows, so the
attempt a worker is writing is never deleted.
"""

import logging
from collections import defaultdict

from ultimatetunes.core.inflight import InFlight
from ultimatetunes.core.storage import StagingStore
from ultimatetunes.errors import PathRejected
from ultimatetunes.jobs.queue import JobQueue
from ultimatetunes.streaming.state import cleanup_plan
from ultimatetunes.streaming.watch import view_of

log = logging.getLogger(__name__)


def listeners_key(job_id: str) -> str:
    """The `InFlight` listener key of a job's streams."""
    return f"stream:job:{job_id}"


class StagingJanitor:
    def __init__(self, jobs: JobQueue, staging: StagingStore, inflight: InFlight) -> None:
        self._jobs = jobs
        self._staging = staging
        self._inflight = inflight

    def _delete(self, rel: str) -> bool:
        try:
            self._staging.delete(rel)
        except (OSError, PathRejected) as exc:
            log.warning("staging cleanup of %s failed: %s", rel, exc)
            return False
        return True

    def clean_job(self, job_id: str) -> int:
        """Deletes the job's staging directories it no longer needs; returns how many."""
        job = self._jobs.get(job_id)
        if job is None:
            return 0
        plan = cleanup_plan(view_of(job), self._inflight.listeners(listeners_key(job_id)))
        if plan.whole:
            return int(self._delete(job_id))
        return sum(self._delete(f"{job_id}/{seq}") for seq in range(1, plan.upto + 1))

    def _present(self) -> dict[str, set[str]]:
        """Job directory → the attempt directories that hold files (`<jobId>/<attemptSeq>/…`)."""
        found: dict[str, set[str]] = defaultdict(set)
        for rel in self._staging.walk():
            parts = rel.split("/")
            if len(parts) >= 3 and parts[1].isdigit():  # noqa: PLR2004 - job/attempt/file
                found[parts[0]].add(parts[1])
        return found

    def sweep(self) -> int:
        """Deletes every attempt directory nobody needs; returns how many."""
        deleted = 0
        for job_id, attempts in sorted(self._present().items()):
            job = self._jobs.get(job_id)
            plan = cleanup_plan(view_of(job), self._inflight.listeners(listeners_key(job_id)))
            if plan.whole:
                deleted += self._delete(job_id)
                continue
            for seq in sorted(attempts):
                if plan.covers(int(seq)):
                    deleted += self._delete(f"{job_id}/{seq}")
        return deleted
