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
  requested in the same transaction (`JobQueue.enqueue_in`), also for a pending track kept
  by its library UUID. Every id is checked before anything is written. At most
  `keep_download_cap()` of the ids may need a download (a `yt:` id without a track, or a
  pending track): one request cannot queue (or look up) more than that, whatever `MAX_IDS`
  allows for songs already in the library. The cap never exceeds the per-user catalog burst
  (`UT_CATALOG_USER_BURST`), so a full keep request fits in one budget. The download limits of
  jobs/gate.py apply too.
"""

import asyncio
from collections.abc import Sequence
from typing import TYPE_CHECKING

from starlette.concurrency import run_in_threadpool

from ultimatetunes.errors import PayloadTooLarge, TunesError
from ultimatetunes.ids.resolve import TrackRef, materialize_song, resolve_track
from ultimatetunes.ids.virtual import VirtualId, parse_kind
from ultimatetunes.jobs.queue import PRIORITY_KEEP
from ultimatetunes.library.render import Obj, pending_child, placeholder_child
from ultimatetunes.library.repository import LibraryRepository
from ultimatetunes.search.catalog import CatalogTrack
from ultimatetunes.search.render import external_child, library_child
from ultimatetunes.search.service import search_settings

if TYPE_CHECKING:
    from ultimatetunes.core.services import Services

# Most ids one request may carry (contracts/errors.md, PayloadTooLarge).
MAX_IDS = 1000
# Most ids of one "keep" request that may start a download (abuse limits), at most the
# per-user catalog burst (`keep_download_cap`).
MAX_KEEP_DOWNLOADS = 50
# Catalog lookups of unknown `yt:` items per request, and how many run at once.
MAX_LOOKUPS = 100
LOOKUP_CONCURRENCY = 4


def keep_download_cap() -> int:
    return min(MAX_KEEP_DOWNLOADS, int(search_settings().catalog_user_burst))


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


def _materialize_and_request(
    services: "Services",
    resolved: dict[str, TrackRef | VirtualId],
    records: Sequence[CatalogTrack],
    user_id: str,
) -> dict[str, TrackRef]:
    """One transaction: the pending tracks of `records` (with their aliases), then a download
    job for every pending track that is kept, however it was named (`yt:` id or library
    UUID). The queue keeps one job per track."""
    with services.db.transaction() as conn:
        new = {t.video_id: materialize_song(conn, services.clock, t) for t in records}
        refs: dict[str, TrackRef] = {
            raw: new[target.payload] if isinstance(target, VirtualId) else target
            for raw, target in resolved.items()
        }
        pending = {ref.id for ref in refs.values() if ref.status == "pending"}
        for track_id in sorted(pending):
            video = conn.execute(
                "SELECT yt_video_id FROM tracks WHERE id = ?", (track_id,)
            ).scalar()
            if video is not None:
                services.jobs.enqueue_in(
                    conn,
                    track_id=track_id,
                    video_id=str(video),
                    priority=PRIORITY_KEEP,
                    requested_by=user_id,
                )
    return refs


async def keep(services: "Services", user_id: str, raw_ids: Sequence[str]) -> list[str]:
    """The library track id of every song id, in order (materializing `yt:` ids)."""
    check_count(raw_ids)
    _parse_songs(raw_ids)
    resolved = await run_in_threadpool(_resolve_keep, services, raw_ids)
    missing = list(dict.fromkeys(r.payload for r in resolved.values() if isinstance(r, VirtualId)))
    pending = {r.id for r in resolved.values() if isinstance(r, TrackRef) and r.status == "pending"}
    cap = keep_download_cap()
    if len(missing) + len(pending) > cap:
        raise PayloadTooLarge(f"At most {cap} songs that are not in the library yet per request")
    # Every external song must exist in the catalog before anything is written.
    records = await asyncio.gather(*(services.catalog.track(v) for v in missing))
    refs = await run_in_threadpool(
        _materialize_and_request, services, resolved, list(records), user_id
    )
    return [refs[raw].id for raw in raw_ids]
