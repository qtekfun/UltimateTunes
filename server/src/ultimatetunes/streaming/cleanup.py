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
attempt a worker is writing is never deleted. The sweep also removes attempt directories left
empty and job directories with nothing left in them (`rmdir`, which refuses a directory that
is not empty).
"""

import logging

from ultimatetunes.core.inflight import InFlight
from ultimatetunes.core.storage import StagingStore
from ultimatetunes.errors import PathRejected
from ultimatetunes.jobs.queue import JobQueue
from ultimatetunes.streaming.state import cleanup_plan
from ultimatetunes.streaming.watch import view_of

log = logging.getLogger(__name__)

# Any valid name: its parent is the staging root.
PROBE = ".janitor"


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
        deleted = sum(self._delete(f"{job_id}/{seq}") for seq in range(1, plan.upto + 1))
        return deleted + self._remove_if_empty(job_id)

    def _directories(self) -> dict[str, set[str]]:
        """Job directory → its attempt directories (`<jobId>/<attemptSeq>/`), empty ones too.
        Listed on the store's directory tree (`local_path`); other entries are left alone."""
        try:
            root = self._staging.local_path(PROBE).parent
            jobs = [e for e in root.iterdir() if e.is_dir() and not e.is_symlink()]
        except (OSError, PathRejected) as exc:
            log.warning("staging sweep cannot list %s: %s", "/staging", exc)
            return {}
        found: dict[str, set[str]] = {}
        for job in sorted(jobs):
            try:
                attempts = {
                    e.name
                    for e in job.iterdir()
                    if e.name.isdigit() and e.is_dir() and not e.is_symlink()
                }
            except OSError:
                continue
            found[job.name] = attempts
        return found

    def _remove_if_empty(self, rel: str) -> bool:
        """`rmdir`: only an empty directory goes (a worker that creates it again is fine)."""
        try:
            self._staging.local_path(rel).rmdir()
        except (OSError, PathRejected):
            return False
        return True

    def sweep(self) -> int:
        """Deletes every attempt directory nobody needs, and job directories left empty;
        returns how many directories went."""
        deleted = 0
        for job_id, attempts in self._directories().items():
            job = self._jobs.get(job_id)
            plan = cleanup_plan(view_of(job), self._inflight.listeners(listeners_key(job_id)))
            if plan.whole:
                deleted += self._delete(job_id)
                continue
            for seq in sorted(attempts, key=int):
                if plan.covers(int(seq)):
                    deleted += self._delete(f"{job_id}/{seq}")
            deleted += self._remove_if_empty(job_id)
        return deleted
