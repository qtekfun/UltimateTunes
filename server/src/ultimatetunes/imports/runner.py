# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Runs imports in the background, inside the api process (RF-08).

Mechanism (stateless api, CLAUDE.md): everything an import needs lives in the database
(`imports`, `import_items`), so any api process can run or resume it. `POST /ut/v1/imports`
stores the import (file imports with all their items) and schedules `run` as a response
background task; `run` goes through the shared `InFlight` registry under `import:<id>`, so one
process never runs the same import twice, and the work is its own task (a client that goes away
does not cancel it). Work is resumable: each item is recorded as soon as it is decided, and a
rerun only looks at the items still `pending`. An import whose runner died (api restart) is
resumed when its owner next reads it (`resume_stale`): still active, not running here, and not
touched for `STALE_AFTER_S`. With several api replicas (phase 5) two replicas could resume the
same stale import at once; that is harmless (every step is idempotent) but wasteful, and a
lease column would settle it then.

States: `queued` → `reading` (YouTube Music URL: read the playlist) → `matching` → `done` (the
user playlist exists) or `failed` (the playlist could not be read). Per item: `matched` (the
song is requested: pending track, `yt:` alias and download job), `not_found`, or `failed` (the
catalog failed for that item; the import goes on).

Requesting a match uses `ids.resolve.materialize_song` in its own transaction and then
`JobQueue.enqueue` (idempotent, one job per track) before the item is recorded, so a crash in
between leaves the item `pending` and a resume repeats both steps harmlessly. Searches are
paced (`UT_IMPORT_SEARCH_INTERVAL_S`) so a long import leaves catalog budget to interactive
search.
"""

import logging
from collections.abc import Callable
from datetime import timedelta
from typing import TYPE_CHECKING

import anyio
from starlette.concurrency import run_in_threadpool

from ultimatetunes.core.clock import Clock, format_ts
from ultimatetunes.db.database import Database
from ultimatetunes.errors import NotFound, TunesError, spec_for
from ultimatetunes.ids.resolve import materialize_song
from ultimatetunes.ids.uuid7 import new_id
from ultimatetunes.imports.files import SourceItem
from ultimatetunes.imports.matching import SEARCH_LIMIT, Match, best_match, core_title, query_for
from ultimatetunes.imports.repository import TERMINAL, ImportRepository, ImportRow, ItemRow
from ultimatetunes.imports.settings import ImportSettings
from ultimatetunes.jobs.queue import PRIORITY_IMPORT, JobQueue
from ultimatetunes.search.catalog import CatalogTrack, MusicCatalog

if TYPE_CHECKING:
    from ultimatetunes.core.inflight import InFlight
    from ultimatetunes.core.services import Services

log = logging.getLogger(__name__)

STALE_AFTER_S = 120
_KEY = "import:"


class ImportRunner:
    def __init__(  # noqa: PLR0913 - the shared services an import uses
        self,
        *,
        db: Database,
        clock: Clock,
        catalog: MusicCatalog,
        jobs: JobQueue,
        inflight: "InFlight",
        settings: ImportSettings | None = None,
    ) -> None:
        self._settings = settings or ImportSettings()
        self._db = db
        self._clock = clock
        self._catalog = catalog
        self._jobs = jobs
        self._inflight = inflight

    @classmethod
    def of(cls, services: "Services") -> "ImportRunner":
        return cls(
            db=services.db,
            clock=services.clock,
            catalog=services.catalog,
            jobs=services.jobs,
            inflight=services.inflight,
            settings=ImportSettings(),
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
        """Runs (or resumes) the import; returns once it is `done` or `failed`."""
        await self._inflight.run(_KEY + import_id, lambda: self._guarded(import_id))

    def stale(self, active: list[tuple[str, str]]) -> list[str]:
        """Of (id, updated_at) pairs of active imports, those to resume now."""
        cutoff = format_ts(self._clock.now() - timedelta(seconds=STALE_AFTER_S))
        return [i for i, updated in active if updated <= cutoff and not self.running(i)]

    async def _guarded(self, import_id: str) -> None:
        try:
            await self._run(import_id)
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
        try:
            playlist = await self._catalog.playlist(str(row.source_playlist_id))
        except TunesError as exc:
            message = (
                "The playlist was not found on YouTube Music (private playlists cannot be read)"
                if isinstance(exc, NotFound)
                else exc.message
            )
            code = spec_for(exc).problem_code or "internal_error"
            await self._write(lambda r: r.fail(row.id, code, message, self._now()))
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
            track = known.get(item.video_id) or await self._catalog.track(item.video_id)
            return Match(track, 1.0)
        found = best_match(item, await self._search(query_for(item)))
        if found is None and core_title(item.title) != item.title:
            found = best_match(item, await self._search(query_for(item, core=True)))
        return found

    async def _search(self, query: str) -> list[CatalogTrack]:
        try:
            return await self._catalog.search_songs(query, SEARCH_LIMIT)
        finally:
            if self._settings.import_search_interval_s > 0:
                await anyio.sleep(self._settings.import_search_interval_s)

    async def _match(self, row: ImportRow, item: ItemRow, known: dict[str, CatalogTrack]) -> None:
        position = item.position
        try:
            found = await self._find(item.source(), known)
        except NotFound:
            found = None
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
