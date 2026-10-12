# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Songs by id for browsing, playlists, stars and the play queue, and the "keep" action.

- `children(services, user, track_ids)`: library track ids (any status) → `Child`s in order.
  Ready tracks are library songs; pending or failed ones show as their external `yt:` song.
- `resolve_children(services, user, raw_ids)`: raw song ids as a client sent them (library
  UUIDs or `yt:` ids, e.g. a saved play queue) → `(raw id, Child)` in order. A `yt:` id with
  no library track is answered from the catalog (cached); when the catalog cannot answer, a
  placeholder keeps the item in the list. Unknown library ids are left out.
- `keep(services, user, raw_ids)`: the "keep" action of contracts/ids.md (star, playlist
  add): every id resolves to a library track; a `yt:` id without one is materialized as a
  `pending` track with its alias (`ids.resolve.materialize_song`) and its download job is
  requested. Every id is checked before anything is written.
"""

import asyncio
from collections.abc import Sequence
from typing import TYPE_CHECKING

from starlette.concurrency import run_in_threadpool

from ultimatetunes.errors import PayloadTooLarge, TunesError
from ultimatetunes.ids.resolve import TrackRef, materialize_song, resolve_track
from ultimatetunes.ids.virtual import SONG_PREFIX, VirtualId, parse_kind
from ultimatetunes.jobs.queue import PRIORITY_KEEP
from ultimatetunes.library.render import Obj, pending_child, placeholder_child
from ultimatetunes.library.repository import LibraryRepository
from ultimatetunes.search.catalog import CatalogTrack
from ultimatetunes.search.render import external_child, library_child

if TYPE_CHECKING:
    from ultimatetunes.core.services import Services

# Most ids one request may carry (contracts/errors.md, PayloadTooLarge).
MAX_IDS = 1000
# Catalog lookups of unknown `yt:` items per request, and how many run at once.
MAX_LOOKUPS = 100
LOOKUP_CONCURRENCY = 4


def check_count(ids: Sequence[str]) -> None:
    if len(ids) > MAX_IDS:
        raise PayloadTooLarge(f"At most {MAX_IDS} ids per request")


def _child_map(services: "Services", user_id: str, track_ids: Sequence[str]) -> dict[str, Obj]:
    with services.db.read() as conn:
        repo = LibraryRepository(conn)
        ready = repo.songs_by_id(user_id, track_ids)
        others = repo.track_rows(user_id, [t for t in track_ids if t not in ready])
    out: dict[str, Obj] = {track_id: library_child(song) for track_id, song in ready.items()}
    for track_id, row in others.items():
        child = pending_child(row)
        if child is not None:
            out[track_id] = child
    return out


async def children(services: "Services", user_id: str, track_ids: Sequence[str]) -> list[Obj]:
    found = await run_in_threadpool(_child_map, services, user_id, track_ids)
    return [found[t] for t in track_ids if t in found]


async def lookup(services: "Services", videos: Sequence[str]) -> dict[str, CatalogTrack]:
    """Catalog records of `videos` (at most `MAX_LOOKUPS`); failures are left out."""
    gate = asyncio.Semaphore(LOOKUP_CONCURRENCY)

    async def one(video: str) -> CatalogTrack | None:
        async with gate:
            try:
                return await services.catalog.track(video)
            except TunesError:
                return None

    unique = list(dict.fromkeys(videos))[:MAX_LOOKUPS]
    found = await asyncio.gather(*(one(v) for v in unique))
    return {t.video_id: t for t in found if t is not None}


def _resolve_all(
    services: "Services", raw_ids: Sequence[str]
) -> dict[str, TrackRef | VirtualId | None]:
    resolved: dict[str, TrackRef | VirtualId | None] = {}
    with services.db.read() as conn:
        for raw in dict.fromkeys(raw_ids):
            try:
                resolved[raw] = resolve_track(conn, raw)
            except TunesError:
                resolved[raw] = None
    return resolved


async def resolve_children(
    services: "Services", user_id: str, raw_ids: Sequence[str]
) -> list[tuple[str, Obj]]:
    resolved = await run_in_threadpool(_resolve_all, services, raw_ids)
    refs = [r.id for r in resolved.values() if isinstance(r, TrackRef)]
    rendered = await run_in_threadpool(_child_map, services, user_id, refs)
    externals = [r.payload for r in resolved.values() if isinstance(r, VirtualId)]
    tracks = await lookup(services, externals) if externals else {}
    out: list[tuple[str, Obj]] = []
    for raw in raw_ids:
        target = resolved.get(raw)
        if isinstance(target, TrackRef):
            child = rendered.get(target.id)
            if child is not None:
                out.append((raw, child))
        elif isinstance(target, VirtualId):
            track = tracks.get(target.payload)
            out.append((raw, external_child(track) if track else placeholder_child(target.text)))
    return out


# ---------------------------------------------------------------------- keep


def _parse_songs(raw_ids: Sequence[str]) -> None:
    for raw in raw_ids:
        parse_kind(raw, "song")


def _resolve_keep(services: "Services", raw_ids: Sequence[str]) -> dict[str, TrackRef | VirtualId]:
    out: dict[str, TrackRef | VirtualId] = {}
    with services.db.read() as conn:
        for raw in dict.fromkeys(raw_ids):
            out[raw] = resolve_track(conn, raw)
    return out


def _materialize(services: "Services", tracks: Sequence[CatalogTrack]) -> dict[str, TrackRef]:
    with services.db.transaction() as conn:
        return {t.video_id: materialize_song(conn, services.clock, t) for t in tracks}


def _request_jobs(services: "Services", refs: Sequence[tuple[TrackRef, str]], user_id: str) -> None:
    for ref, video in refs:
        if ref.status == "pending":
            services.jobs.enqueue(
                track_id=ref.id, video_id=video, priority=PRIORITY_KEEP, requested_by=user_id
            )


async def keep(services: "Services", user_id: str, raw_ids: Sequence[str]) -> list[str]:
    """The library track id of every song id, in order (materializing `yt:` ids)."""
    check_count(raw_ids)
    _parse_songs(raw_ids)
    resolved = await run_in_threadpool(_resolve_keep, services, raw_ids)
    missing = list(dict.fromkeys(r.payload for r in resolved.values() if isinstance(r, VirtualId)))
    new: dict[str, TrackRef] = {}
    if missing:
        # Every external song must exist in the catalog before anything is written.
        records = await asyncio.gather(*(services.catalog.track(v) for v in missing))
        new = await run_in_threadpool(_materialize, services, records)
    refs: dict[str, TrackRef] = {
        raw: new[target.payload] if isinstance(target, VirtualId) else target
        for raw, target in resolved.items()
    }
    # A `yt:` id kept while its track is pending gets its download requested (one job per
    # track: the queue deduplicates).
    wanted = {
        refs[raw].id: (refs[raw], raw[len(SONG_PREFIX) :])
        for raw in refs
        if raw.startswith(SONG_PREFIX)
    }
    await run_in_threadpool(_request_jobs, services, list(wanted.values()), user_id)
    return [refs[raw].id for raw in raw_ids]
