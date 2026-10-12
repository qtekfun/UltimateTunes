# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Runs imports in the background, inside the api process (RF-08).

Mechanism (stateless api, CLAUDE.md): everything an import needs lives in the database
(`imports`, `import_items`), so any api process can run or resume it. `POST /ut/v1/imports`
stores the import (file imports with all their items) and schedules `run` as a response
background task; `run` goes through the shared `InFlight` registry under `import:<id>`, so one
process never runs the same import twice, and the work is its own task (a client that goes away
does not cancel it). Work is resumable: each item is recorded as soon as it is decided, and a
rerun only looks at the items still `pending`. An import whose run stopped is resumed when its
owner next reads it (`routes._resume`): still active, not running here, and not touched for
`STALE_AFTER_S`. With several api replicas (phase 5) two replicas could resume the same stale
import at once: every step is idempotent, so the database stays consistent, but the work and
its catalog calls are done twice; a lease column would settle that then.

A run stops early, leaving the import active and the current item `pending`, when:
- YouTube Music is throttling or unreachable (`CatalogThrottled`, `RetryLater`, and
  `CatalogUnavailable`, which covers network errors and 5xx but also other 4xx answers): the
  next resume tries again instead of failing items for a passing outage. Each pause is counted
  on the item (or on the import for the playlist read); at `MAX_PAUSES` the item fails (or the
  import fails), so an error that repeats for one query never keeps an import running. A
  response that cannot be read (`CatalogParseError`) is not passing: it fails the item at once;
- the api shuts down (SIGTERM): uvicorn waits for running requests, background tasks included,
  for its graceful-shutdown timeout and then cancels them; a cancelled run is logged and the
  import is resumed after the restart. (The api's lifespan is coordinator-owned and has no task
  group; nothing is lost by cancelling, since all progress is already in the database.)

Load: every catalog call of every import first takes a token from one shared `RateLimiter`
bucket (`import:catalog`, `UT_IMPORT_CATALOG_RATE_PER_S`), waiting for it when there is none,
so imports together never use more than their share of the catalog's 2 req/s and interactive
search keeps the rest. Resumed YouTube Music imports (track lookups) are paced the same way.

States: `queued` → `reading` (YouTube Music URL: read the playlist) → `matching` → `done` (the
user playlist exists) or `failed` (the playlist does not exist, or a bug). Per item: `matched`
(the song is requested: pending track, `yt:` alias and download job), `not_found`, or `failed`
(the catalog refused that item for good).

Requesting a match uses `ids.resolve.materialize_song` in its own transaction and then
`JobQueue.enqueue` (idempotent, one job per track) before the item is recorded, so a crash in
between leaves the item `pending` and a resume repeats both steps harmlessly.
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import TYPE_CHECKING

import anyio
from starlette.concurrency import run_in_threadpool

from ultimatetunes.core.clock import Clock, format_ts
from ultimatetunes.core.ratelimit import Limit, RateLimiter
from ultimatetunes.db.database import Database
from ultimatetunes.errors import NotFound, RetryLater, TunesError, UpstreamUnavailable, spec_for
from ultimatetunes.ids.resolve import materialize_song
from ultimatetunes.ids.uuid7 import new_id
from ultimatetunes.imports.files import SourceItem
from ultimatetunes.imports.matching import SEARCH_LIMIT, Match, best_match, core_title, query_for
from ultimatetunes.imports.repository import TERMINAL, ImportRepository, ImportRow, ItemRow
from ultimatetunes.imports.settings import ImportSettings
from ultimatetunes.jobs.queue import PRIORITY_IMPORT, JobQueue
from ultimatetunes.search.catalog import CatalogParseError, CatalogTrack, MusicCatalog

if TYPE_CHECKING:
    from ultimatetunes.core.inflight import InFlight
    from ultimatetunes.core.services import Services

log = logging.getLogger(__name__)

STALE_AFTER_S = 120
BUCKET = "import:catalog"
_KEY = "import:"
MAX_PAUSES = 5
# Errors that mean "YouTube Music cannot answer now": pause the run, retry on resume.
_PASSING = (UpstreamUnavailable, RetryLater)
_LASTING = (CatalogParseError,)


class _Paused(Exception):  # noqa: N818 - a signal, not an error
    """The catalog is unavailable: stop this run, leave the rest pending."""


class ImportRunner:
    def __init__(  # noqa: PLR0913 - the shared services an import uses
        self,
        *,
        db: Database,
        clock: Clock,
        catalog: MusicCatalog,
        jobs: JobQueue,
        inflight: "InFlight",
        limiter: RateLimiter,
        settings: ImportSettings | None = None,
    ) -> None:
        settings = settings or ImportSettings()
        self._limit = Limit(settings.import_catalog_rate_per_s, settings.import_catalog_burst)
        self._db = db
        self._clock = clock
        self._catalog = catalog
        self._jobs = jobs
        self._inflight = inflight
        self._limiter = limiter

    @classmethod
    def of(cls, services: "Services") -> "ImportRunner":
        return cls(
            db=services.db,
            clock=services.clock,
            catalog=services.catalog,
            jobs=services.jobs,
            inflight=services.inflight,
            limiter=services.rate_limiter,
        )

    def _now(self) -> str:
        return format_ts(self._clock.now())

    async def _write[T](self, work: Callable[[ImportRepository], T]) -> T:
        def call() -> T:
            with self._db.transaction() as conn:
                return work(ImportRepository(conn))

        return await run_in_threadpool(call)

    def running(self, import_id: str) -> bool:
        return self._inflight.running(_KEY + import_id)

    async def run(self, import_id: str) -> None:
        """Runs (or resumes) the import until it ends or pauses."""
        await self._inflight.run(_KEY + import_id, lambda: self._guarded(import_id))

    def stale(self, active: list[tuple[str, str]]) -> list[str]:
        """Of (id, updated_at) pairs of active imports, those to resume now."""
        cutoff = format_ts(self._clock.now() - timedelta(seconds=STALE_AFTER_S))
        return [i for i, updated in active if updated <= cutoff and not self.running(i)]

    async def _catalog_call[T](self, call: Callable[[], Awaitable[T]]) -> T:
        """One catalog call under the shared import budget; passing outages pause the run."""
        while True:
            decision = await run_in_threadpool(self._limiter.hit, BUCKET, self._limit)
            if decision.allowed:
                break
            await anyio.sleep(decision.retry_after_s)
        try:
            return await call()
        except _LASTING:
            raise
        except _PASSING as exc:
            raise _Paused(exc.message) from exc

    async def _guarded(self, import_id: str) -> None:
        try:
            await self._run(import_id)
        except _Paused as paused:
            log.info("import %s paused: %s", import_id, paused)
        except anyio.get_cancelled_exc_class():
            log.info("import %s stopped by shutdown; it resumes later", import_id)
            raise
        except Exception as exc:  # the import must end, whatever broke
            log.exception("import %s failed", import_id)
            code = spec_for(exc).problem_code if isinstance(exc, TunesError) else None
            message = exc.message if isinstance(exc, TunesError) else "Internal error"
            await self._write(
                lambda r: r.fail(import_id, code or "internal_error", message, self._now())
            )

    async def _run(self, import_id: str) -> None:
        row = await self._write(lambda r: r.get(import_id))
        if row is None or row.state in TERMINAL:
            return
        known: dict[str, CatalogTrack] = {}
        if row.source == "ytmusic" and row.state in ("queued", "reading"):
            read = await self._read(row)
            if read is None:
                return
            known = read
        await self._write(lambda r: r.set_state(import_id, "matching", self._now()))
        pending = await self._write(lambda r: r.pending_items(import_id))
        for item in pending:
            await self._match(row, item, known)
        await self._write(lambda r: r.finish(import_id, new_id(self._clock), self._now()))

    async def _read(self, row: ImportRow) -> dict[str, CatalogTrack] | None:
        """Reads a YouTube Music playlist into items; None when the import failed."""
        await self._write(lambda r: r.set_state(row.id, "reading", self._now()))
        playlist_id = str(row.source_playlist_id)
        try:
            playlist = await self._catalog_call(lambda: self._catalog.playlist(playlist_id))
        except _Paused as paused:
            if await self._write(lambda r: r.pause_read(row.id, self._now())) < MAX_PAUSES:
                raise
            message = f"YouTube Music kept failing: {paused}"
            await self._write(
                lambda r: r.fail(row.id, "upstream_unavailable", message, self._now())
            )
            return None
        except NotFound:
            message = (
                "The playlist was not found on YouTube Music (private playlists cannot be read)"
            )
            await self._write(lambda r: r.fail(row.id, "not_found", message, self._now()))
            return None
        items = [
            SourceItem(
                t.title,
                tuple(a.name for a in t.artists),
                t.album.name if t.album else None,
                t.duration_s,
                video_id=t.video_id,
            )
            for t in playlist.tracks
        ]

        def store(r: ImportRepository) -> None:
            now = self._now()
            r.add_items(row.id, items, now)
            r.set_default_name(row.id, playlist.title, now)
            r.set_state(row.id, "matching", now)

        await self._write(store)
        return {t.video_id: t for t in playlist.tracks}

    async def _find(self, item: SourceItem, known: dict[str, CatalogTrack]) -> Match | None:
        if item.video_id is not None:
            video_id = item.video_id
            track = known.get(video_id)
            if track is None:
                track = await self._catalog_call(lambda: self._catalog.track(video_id))
            return Match(track, 1.0)
        found = best_match(item, await self._search(query_for(item)))
        if found is None and core_title(item.title) != item.title:
            found = best_match(item, await self._search(query_for(item, core=True)))
        return found

    async def _search(self, query: str) -> list[CatalogTrack]:
        return await self._catalog_call(lambda: self._catalog.search_songs(query, SEARCH_LIMIT))

    async def _match(self, row: ImportRow, item: ItemRow, known: dict[str, CatalogTrack]) -> None:
        position = item.position
        try:
            found = await self._find(item.source(), known)
        except NotFound:
            found = None
        except _Paused as paused:
            pauses = await self._write(lambda r: r.pause_item(row.id, position, self._now()))
            if pauses < MAX_PAUSES:
                raise
            message = f"YouTube Music kept failing: {paused}"
            await self._write(
                lambda r: r.record_item(
                    row.id, position, state="failed", now=self._now(), error=message
                )
            )
            return
        except TunesError as exc:
            message = exc.message
            await self._write(
                lambda r: r.record_item(
                    row.id, position, state="failed", now=self._now(), error=message
                )
            )
            return
        if found is None:
            await self._write(
                lambda r: r.record_item(row.id, position, state="not_found", now=self._now())
            )
            return
        track_id = await self._request(row.user_id, found.track)
        await self._write(
            lambda r: r.record_item(
                row.id,
                position,
                state="matched",
                now=self._now(),
                score=found.score,
                video_id=found.track.video_id,
                track_id=track_id,
            )
        )

    async def _request(self, user_id: str, track: CatalogTrack) -> str:
        """Keeps the song: pending track + alias, then its download job (unless archived)."""

        def keep() -> str:
            with self._db.transaction() as conn:
                ref = materialize_song(conn, self._clock, track)
            if ref.status == "pending":
                self._jobs.enqueue(
                    track_id=ref.id,
                    video_id=track.video_id,
                    priority=PRIORITY_IMPORT,
                    requested_by=user_id,
                )
            return ref.id

        return await run_in_threadpool(keep)
