# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Keep a track and follow its download (`/ut/v1/tracks/{id}/request` and `/status`, RF-04).

- `status(id)`: the contract's `TrackStatus`. A `yt:` id without a library track (or a pending
  track nobody requested) is `not_requested`; a library track without a job (a scanned file)
  is `ready`; otherwise the job's state, progress, attempts and last error. `streamable` says
  whether `/rest/stream` would start now (`streaming.state.plan_start`).
- `request(id, reason)`: materializes a `yt:` id (`ids.resolve.materialize_song`) and queues
  its download in the same transaction (`JobQueue.enqueue_in`, deduplicated per track; a
  failed or cancelled job is queued again with its attempts reset). Nothing is queued for a
  track that is already `ready`.
"""

from dataclasses import dataclass
from typing import Literal

from ultimatetunes.core.services import Services
from ultimatetunes.db.driver import Connection
from ultimatetunes.errors import NotFound
from ultimatetunes.ids.resolve import TrackRef, materialize_song, resolve_track
from ultimatetunes.ids.virtual import VirtualId
from ultimatetunes.jobs.queue import PRIORITY_KEEP, PRIORITY_PREFETCH, Job, _Jobs
from ultimatetunes.search.catalog import CatalogTrack
from ultimatetunes.streaming.state import Start, plan_start
from ultimatetunes.streaming.watch import view_of

Reason = Literal["keep", "prefetch"]
PRIORITIES: dict[str, int] = {"keep": PRIORITY_KEEP, "prefetch": PRIORITY_PREFETCH}
DEFAULT_MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class TrackStatus:
    id: str
    track_id: str | None
    state: str
    progress: float
    attempts: int
    max_attempts: int
    error: dict[str, str] | None
    streamable: bool
    updated_at: str | None

    def to_json(self) -> dict[str, object]:
        return {
            "id": self.id,
            "trackId": self.track_id,
            "state": self.state,
            "progress": self.progress,
            "attempts": self.attempts,
            "maxAttempts": self.max_attempts,
            "error": self.error,
            "streamable": self.streamable,
            "updatedAt": self.updated_at,
        }


def _not_requested(raw: str, track_id: str | None) -> TrackStatus:
    return TrackStatus(
        id=raw,
        track_id=track_id,
        state="not_requested",
        progress=0.0,
        attempts=0,
        max_attempts=DEFAULT_MAX_ATTEMPTS,
        error=None,
        streamable=False,
        updated_at=None,
    )


def _error(job: Job) -> dict[str, str] | None:
    if job.error_code is None or job.state in ("ready", "downloading", "tagging"):
        return None
    return {"code": job.error_code, "message": job.error_message or job.error_code}


def _of_job(raw: str, job: Job) -> TrackStatus:
    ready = job.state == "ready"
    return TrackStatus(
        id=raw,
        track_id=job.track_id,
        state=job.state,
        progress=1.0 if ready else min(max(job.progress, 0.0), 1.0),
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        error=_error(job),
        streamable=ready or isinstance(plan_start(view_of(job)), Start),
        updated_at=job.updated_at,
    )


def _status_in(conn: Connection, raw: str) -> TrackStatus:
    target = resolve_track(conn, raw)
    if isinstance(target, VirtualId):
        return _not_requested(raw, None)
    row = conn.execute("SELECT updated_at FROM tracks WHERE id = ?", (target.id,)).fetchone()
    job = _Jobs(conn).by_track("download", target.id)
    if target.status == "ready" and (job is None or job.state != "ready"):
        # A scanned (or merged-into) library file: nothing to download.
        updated = None if row is None else str(row["updated_at"])
        attempts = 0 if job is None else job.attempts
        return TrackStatus(
            id=raw,
            track_id=target.id,
            state="ready",
            progress=1.0,
            attempts=attempts,
            max_attempts=DEFAULT_MAX_ATTEMPTS if job is None else job.max_attempts,
            error=None,
            streamable=True,
            updated_at=updated,
        )
    if job is None:
        return _not_requested(raw, target.id)
    return _of_job(raw, job)


def status(services: Services, raw: str) -> TrackStatus:
    with services.db.read() as conn:
        return _status_in(conn, raw)


def resolve(services: Services, raw: str) -> TrackRef | VirtualId:
    with services.db.read() as conn:
        return resolve_track(conn, raw)


def request_in(  # noqa: PLR0913 - the resolved request and who asks
    services: Services,
    raw: str,
    target: TrackRef | VirtualId,
    track: CatalogTrack | None,
    *,
    reason: Reason,
    user_id: str,
) -> tuple[bool, TrackStatus]:
    """(queued, status) after requesting `raw`; `queued` is False when it is already ready."""
    with services.db.transaction() as conn:
        if track is not None:
            ref = materialize_song(conn, services.clock, track)
            video: str | None = track.video_id
        elif isinstance(target, TrackRef):
            ref = target
            stored = conn.execute("SELECT yt_video_id FROM tracks WHERE id = ?", (ref.id,)).scalar()
            video = None if stored is None else str(stored)
        else:
            raise NotFound("Song not found")
        if ref.status == "ready":
            return False, _status_in(conn, raw)
        if video is None:
            raise NotFound("The song has no YouTube Music source to download")
        services.jobs.enqueue_in(
            conn,
            track_id=ref.id,
            video_id=video,
            priority=PRIORITIES[reason],
            requested_by=user_id,
        )
        return True, _status_in(conn, raw)
