# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""`StreamingWhileDownloading`: the `PendingStreams` of the library's `stream`/`download`
(`library.stream`), for songs without an archived file (RF-05, SPEC section 11).

A `GET` of such a song:

1. requests the download: a `yt:` id without a library track is materialized (pending track
   and alias, `ids.resolve.materialize_song`) and its job enqueued in the same transaction; a
   pending track gets its job (or joins it, raising its priority to `stream`);
2. takes a listener slot of the job and of the API key (`InFlight`); beyond the caps,
   `TooManyListeners` (HTTP 503 with `Retry-After`, error 0);
3. waits for the worker's first servable report (`state.plan_start`), then answers at once:
   exact size known → `200` with `Content-Length` and `Accept-Ranges: bytes`, or `206`/`416`
   for a `Range`; size unknown → `200` chunked with `Accept-Ranges: none`, `Range` ignored.
   `Cache-Control: no-store` (the bytes are the raw download, not the archived file);
4. sends the bytes as the worker reports them (`state.step`) and cuts the transfer when the
   job fails or its bytes change (`response.TailResponse`).

A job that fails before the first byte answers error 70 with HTTP 404 (`StreamFailed`); one
archived meanwhile answers from the library file. A `HEAD` never requests anything: it answers
the headers of the running download if there is one, else `200` with no length.
"""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass, replace
from functools import partial
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, BinaryIO

import anyio
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from ultimatetunes.core.services import Services
from ultimatetunes.errors import NotFound, PathRejected, StreamFailed, TooManyListeners
from ultimatetunes.ids.resolve import TrackRef, materialize_song, resolve_track
from ultimatetunes.ids.virtual import VirtualId
from ultimatetunes.jobs.queue import PRIORITY_STREAM, Job
from ultimatetunes.library.stream import (
    CHUNK,
    CONTENT_TYPES,
    RangeNotSatisfiableError,
    attachment,
    file_response,
    parse_range,
)
from ultimatetunes.search.catalog import CatalogTrack
from ultimatetunes.streaming.cleanup import StagingJanitor, listeners_key
from ultimatetunes.streaming.response import StreamAborted, TailResponse
from ultimatetunes.streaming.settings import StreamingSettings
from ultimatetunes.streaming.state import (
    Abort,
    Archived,
    Cursor,
    Done,
    Fail,
    Follow,
    Read,
    Start,
    Wait,
    plan_start,
    step,
)
from ultimatetunes.streaming.watch import JobWatch, Watcher, view_of

if TYPE_CHECKING:
    from ultimatetunes.subsonic.router import SubsonicRequest

log = logging.getLogger(__name__)

# How often a request waiting for its first byte checks that its client is still there.
DISCONNECT_CHECK_S = 1.0
# How long reported bytes may stay unreadable (a slow shared volume) before the stream is cut.
MISSING_BYTES_GRACE_S = 10.0


@dataclass(frozen=True)
class Answer:
    status: int
    headers: dict[str, str]
    cursor: Cursor | None  # None: no body (416)


def respond(start: Start, range_header: str | None, *, download: bool) -> Answer:
    """Status, headers and the listener's cursor of a response to `start`."""
    headers = {"Cache-Control": "no-store", "Content-Type": start.content_type}
    if download:
        headers["Content-Disposition"] = attachment(PurePosixPath(start.final_path).name)
    cursor = Cursor(start.attempt_seq, start.format_id, start.size, 0, start.size)
    if start.size is None:
        # Chunked: no length, `Range` ignored (never an estimate, never `bytes 0-*/*`).
        headers["Accept-Ranges"] = "none"
        return Answer(200, headers, cursor)
    headers["Accept-Ranges"] = "bytes"
    try:
        byte_range = parse_range(range_header, start.size)
    except RangeNotSatisfiableError:
        return Answer(
            416,
            {
                "Accept-Ranges": "bytes",
                "Cache-Control": "no-store",
                "Content-Range": f"bytes */{start.size}",
            },
            None,
        )
    if byte_range is None:
        headers["Content-Length"] = str(start.size)
        return Answer(200, headers, cursor)
    headers["Content-Length"] = str(byte_range.length)
    headers["Content-Range"] = f"bytes {byte_range.start}-{byte_range.end}/{start.size}"
    return Answer(206, headers, replace(cursor, offset=byte_range.start, end=byte_range.end + 1))


def headers_only(status: int, headers: dict[str, str]) -> Response:
    """A response with exactly these headers and no body (no invented `Content-Length`)."""
    response = Response(status_code=status)
    response.raw_headers = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return response


class _Reader:
    """The open staging file of one listener (runs in a worker thread)."""

    def __init__(self, open_read: Callable[[str], BinaryIO]) -> None:
        self._open_read = open_read
        self._handle: BinaryIO | None = None
        self._attempt: int | None = None

    def _open(self, paths: tuple[str, ...]) -> BinaryIO | None:
        for path in paths:
            try:
                return self._open_read(path)
            except FileNotFoundError:
                continue
        return None

    def read(self, attempt: int, move: Read) -> bytes:
        if self._handle is None or self._attempt != attempt:
            self.close()
            self._handle = self._open(move.paths)
            if self._handle is None:
                return b""
            self._attempt = attempt
        if self._handle.tell() != move.offset:
            self._handle.seek(move.offset)
        return self._handle.read(min(CHUNK, move.length))

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
        self._handle = None
        self._attempt = None


class StreamingWhileDownloading:
    def __init__(
        self,
        services: Services,
        settings: StreamingSettings,
        watch: JobWatch,
        janitor: StagingJanitor,
    ) -> None:
        self._services = services
        self._settings = settings
        self._watch = watch
        self._janitor = janitor

    # ------------------------------------------------------------------ PendingStreams

    async def serve(
        self,
        req: "SubsonicRequest",
        target: TrackRef | VirtualId,
        *,
        video: str | None,
        download: bool,
        head: bool,
    ) -> Response:
        if video is None:
            raise NotFound("Song not found")
        if head:
            return await self._head(req, target, video, download=download)
        job_id = await self._request(req, target, video)
        if job_id is None:
            return await self._library(req, download=download)
        response = await self._stream(req, job_id, download=download)
        return await self._library(req, download=download) if response is None else response

    # ------------------------------------------------------------------ request the download

    async def _request(
        self, req: "SubsonicRequest", target: TrackRef | VirtualId, video: str
    ) -> str | None:
        """The job id of the song's download (requested now if needed); None once archived."""
        track = None
        if isinstance(target, VirtualId):
            # Unknown ids are `NotFound` before anything is written.
            track = await self._services.catalog.track(video)
        return await run_in_threadpool(self._enqueue, target, video, track, req.user.user_id)

    def _enqueue(
        self,
        target: TrackRef | VirtualId,
        video: str,
        track: CatalogTrack | None,
        user_id: str,
    ) -> str | None:
        svc = self._services
        with svc.db.transaction() as conn:
            if track is not None:
                ref = materialize_song(conn, svc.clock, track)
                video = track.video_id
            elif isinstance(target, TrackRef):
                ref = target
            else:  # a virtual id always comes with its catalog record
                raise NotFound("Song not found")
            if ref.status == "failed":
                raise StreamFailed()
            if ref.status != "pending":
                return None
            job = svc.jobs.enqueue_in(
                conn,
                track_id=ref.id,
                video_id=video,
                priority=PRIORITY_STREAM,
                requested_by=user_id,
            )
            return job.id

    # ------------------------------------------------------------------ HEAD

    def _job_of(self, track_id: str) -> Job | None:
        with self._services.db.read() as conn:
            found = conn.execute(
                "SELECT id FROM jobs WHERE kind = 'download' AND track_id = ?", (track_id,)
            ).scalar()
        return None if found is None else self._services.jobs.get(str(found))

    async def _head(
        self,
        req: "SubsonicRequest",
        target: TrackRef | VirtualId,
        video: str,
        *,
        download: bool,
    ) -> Response:
        job = None
        if isinstance(target, VirtualId):
            # Checked like a GET (an unknown id is not found), but nothing is written: a
            # virtual id has no track, so no job either.
            await self._services.catalog.track(video)
        else:
            job = await run_in_threadpool(self._job_of, target.id)
        plan = plan_start(view_of(job)) if job is not None else Wait()
        if isinstance(plan, Fail):
            raise StreamFailed()
        if isinstance(plan, Archived):
            return await self._library(req, download=download)
        if isinstance(plan, Wait):
            # Nothing is known yet, and a HEAD never starts a download.
            return headers_only(200, {"Accept-Ranges": "none", "Cache-Control": "no-store"})
        answer = respond(plan, req.request.headers.get("range"), download=download)
        if answer.cursor is None:
            return Response(status_code=answer.status, headers=answer.headers)
        return headers_only(answer.status, answer.headers)

    # ------------------------------------------------------------------ GET

    def _key_listeners(self, req: "SubsonicRequest") -> str:
        principal = req.user
        return f"stream:key:{principal.api_key_id or 'user:' + principal.user_id}"

    async def _admit(self, stack: AsyncExitStack, req: "SubsonicRequest", job_id: str) -> None:
        inflight = self._services.inflight
        on_job = await stack.enter_async_context(inflight.listen(listeners_key(job_id)))
        on_key = await stack.enter_async_context(inflight.listen(self._key_listeners(req)))
        if (
            on_job > self._settings.max_listeners_per_job
            or on_key > self._settings.max_listeners_per_key
        ):
            raise TooManyListeners(self._settings.listener_retry_after_s)

    async def _wait_start(
        self, req: "SubsonicRequest", watcher: Watcher
    ) -> Start | Archived | None:
        """The plan once the job has bytes to serve; None when the client went away."""
        while True:
            view, changed = watcher.current()
            plan = plan_start(view)
            if isinstance(plan, Fail):
                raise StreamFailed()
            if not isinstance(plan, Wait):
                return plan
            with anyio.move_on_after(DISCONNECT_CHECK_S):
                await changed.wait()
            if await req.request.is_disconnected():
                return None

    async def _release(self, stack: AsyncExitStack, job_id: str) -> None:
        await stack.aclose()
        if self._services.inflight.listeners(listeners_key(job_id)) == 0:
            try:
                await run_in_threadpool(self._janitor.clean_job, job_id)
            except Exception:
                log.exception("staging cleanup of job %s failed", job_id)

    async def _stream(
        self, req: "SubsonicRequest", job_id: str, *, download: bool
    ) -> Response | None:
        """The response for a listener of `job_id`; None when the job got archived meanwhile."""
        stack = AsyncExitStack()
        handed_over = False
        try:
            await self._admit(stack, req, job_id)
            watcher = await stack.enter_async_context(self._watch.watch(job_id))
            plan = await self._wait_start(req, watcher)
            if plan is None:
                return Response(status_code=200)  # nobody is listening any more
            if isinstance(plan, Archived):
                return None
            answer = respond(plan, req.request.headers.get("range"), download=download)
            if answer.cursor is None:
                return Response(status_code=answer.status, headers=answer.headers)
            # From here on the response owns the listener slots and releases them.
            response = TailResponse(
                self._tail(watcher, answer.cursor),
                status_code=answer.status,
                headers=answer.headers,
                release=partial(self._release, stack.pop_all(), job_id),
            )
            handed_over = True
            return response
        finally:
            if not handed_over:
                await self._release(stack, job_id)

    async def _tail(self, watcher: Watcher, cursor: Cursor) -> AsyncIterator[bytes]:
        reader = _Reader(self._services.staging.open_read)
        misses = 0
        max_misses = max(1, round(MISSING_BYTES_GRACE_S / self._settings.stream_poll_interval_s))
        try:
            while True:
                view, changed = watcher.current()
                move = step(cursor, view)
                if isinstance(move, Done):
                    return
                if isinstance(move, Abort):
                    log.warning("stream of job %s cut: %s", watcher.job_id, move.reason)
                    raise StreamAborted(move.reason)
                if isinstance(move, Follow):
                    cursor = move.cursor
                    continue
                if isinstance(move, Wait):
                    await changed.wait()
                    continue
                try:
                    chunk = await anyio.to_thread.run_sync(reader.read, cursor.attempt_seq, move)
                except (OSError, PathRejected) as exc:
                    log.warning("stream of job %s cut: %s", watcher.job_id, exc)
                    raise StreamAborted("the staging file is unreadable") from exc
                if chunk:
                    misses = 0
                    cursor = cursor.advanced(len(chunk))
                    yield chunk
                    continue
                misses += 1
                if misses > max_misses:
                    log.warning("stream of job %s cut: reported bytes missing", watcher.job_id)
                    raise StreamAborted("reported bytes are missing")
                with anyio.move_on_after(self._settings.stream_poll_interval_s):
                    await changed.wait()
        finally:
            reader.close()

    # ------------------------------------------------------------------ archived meanwhile

    def _locate(self, raw: str) -> tuple[str, str]:
        with self._services.db.read() as conn:
            target = resolve_track(conn, raw)
            if isinstance(target, VirtualId):
                raise NotFound("Song not found")
            if target.status == "failed":
                raise StreamFailed()
            row = conn.execute(
                "SELECT path, format, content_type FROM tracks WHERE id = ?", (target.id,)
            ).fetchone()
        if row is None or row["path"] is None:
            raise NotFound("Song file is missing")
        fmt = str(row["format"] or "")
        content_type = row["content_type"] or CONTENT_TYPES.get(fmt, "application/octet-stream")
        return str(row["path"]), str(content_type)

    async def _library(self, req: "SubsonicRequest", *, download: bool) -> Response:
        """The archived file (the `yt:` id is an alias of the library track now)."""
        path, content_type = await run_in_threadpool(self._locate, req.require("id"))
        store = self._services.library
        try:
            size = await run_in_threadpool(store.size, path)
        except (OSError, PathRejected):
            raise NotFound("Song file is missing") from None
        extra = {"Content-Disposition": attachment(PurePosixPath(path).name)} if download else {}
        return file_response(
            store,
            path,
            size=size,
            content_type=content_type,
            range_header=req.request.headers.get("range"),
            extra_headers=extra,
        )
