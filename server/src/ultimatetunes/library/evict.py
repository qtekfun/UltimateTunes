# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Library size limit: free the audio of the least played tracks (SPEC section 11, D16).

The admin sets a maximum size for the archived audio in the panel (Library page, the
`settings` table; off until set). Every `UT_LIBRARY_EVICT_INTERVAL_S` the api adds up the
`size_bytes` of the `ready` tracks; above the maximum it frees tracks until the total is at or
below `LOW_WATER` of it, so one new download does not free one track each time.

Order: fewest plays (all users together) first, then the one not played for longest (never
played first), then the oldest archived. Never freed:
- a track starred by anyone, or on an album or by an artist starred by anyone;
- a track without a YouTube video (it could not be downloaded again);
- a track archived less than the grace period ago (default 30 days): a new song has no plays;
- a track with a download or a merge into it in progress.

Freeing keeps the track: its row goes back to `pending` without a file (`refetch.RESET_TRACK`),
so plays, stars, playlists and lyrics stay, and the next play downloads it again while it
streams. Its download job row is dropped, so that play queues a fresh one. Albums and artists
whose tracks are all freed drop out of browsing until one is played again.

Each track is freed in its own transaction that re-checks every rule, so a star, a play or a
download that lands meanwhile wins. The row is committed before the file is deleted; a file that
cannot be removed is logged and left on disk, as with the panel's Delete (a later library scan
registers it as a separate track by its path). Several replicas running at once may free a
little more than needed, never a protected track.
"""

import json
import logging
from dataclasses import dataclass
from datetime import timedelta

import anyio
from starlette.concurrency import run_in_threadpool

from ultimatetunes.auth.repository import AuditEntry, AuditRepository
from ultimatetunes.core.clock import Clock, format_ts
from ultimatetunes.core.storage import LibraryStore
from ultimatetunes.db.database import Database
from ultimatetunes.db.driver import Connection
from ultimatetunes.errors import PathRejected
from ultimatetunes.ids.uuid7 import new_id
from ultimatetunes.library.refetch import RESET_TRACK

log = logging.getLogger(__name__)

KEY_MAX_BYTES = "library_max_bytes"
KEY_GRACE_DAYS = "library_evict_grace_days"
KEY_LAST_RUN = "library_evict_last_run"
DEFAULT_GRACE_DAYS = 30
MAX_GRACE_DAYS = 3650
# Free down to this share of the maximum.
LOW_WATER = 0.9

# A track that may be freed now; `?` is the grace cutoff (archived before it).
_EVICTABLE = (
    "t.status = 'ready' AND t.path IS NOT NULL AND t.size_bytes IS NOT NULL"
    " AND t.yt_video_id IS NOT NULL AND COALESCE(t.archived_at, t.created_at) < ?"
    " AND NOT EXISTS (SELECT 1 FROM starred_tracks st WHERE st.track_id = t.id)"
    " AND NOT EXISTS (SELECT 1 FROM starred_albums sa WHERE sa.album_id = t.album_id)"
    " AND NOT EXISTS (SELECT 1 FROM starred_artists sr WHERE sr.artist_id = t.artist_id)"
    " AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.state IN ('downloading', 'tagging')"
    " AND (j.track_id = t.id OR j.merge_into_track_id = t.id))"
)

# Least played first. COALESCE: an empty string sorts before any timestamp on both databases,
# where a NULL would sort first on SQLite and last on PostgreSQL.
# Built from this module's constants only, never from input.
_CANDIDATES = (
    "SELECT t.id, t.title, t.artist_name, t.path, t.size_bytes,"  # noqa: S608  # nosec B608
    " COALESCE(SUM(s.play_count), 0) AS plays, COALESCE(MAX(s.last_played_at), '') AS last_played"
    " FROM tracks t LEFT JOIN user_track_stats s ON s.track_id = t.id"
    f" WHERE {_EVICTABLE}"
    " GROUP BY t.id, t.title, t.artist_name, t.path, t.size_bytes, t.archived_at, t.created_at"
    " ORDER BY plays ASC, last_played ASC, COALESCE(t.archived_at, t.created_at) ASC, t.id ASC"
)

# `RESET_TRACK` ends with `WHERE id = ? AND status = 'ready'`; the same rules again, on the row.
_FREE = (
    RESET_TRACK  # noqa: S608  # nosec B608 - constants only
    + " AND path = ? AND id IN (SELECT t.id FROM tracks t WHERE t.id = ? AND "
    + _EVICTABLE
    + ")"
)


@dataclass(frozen=True)
class Policy:
    """The admin's limit: `max_bytes` None is off."""

    max_bytes: int | None
    grace_days: int = DEFAULT_GRACE_DAYS


@dataclass(frozen=True)
class Candidate:
    track_id: str
    title: str
    artist: str
    path: str
    size_bytes: int
    plays: int
    last_played: str | None


@dataclass(frozen=True)
class Plan:
    """What a run would free now. `candidates` holds the tracks to free when over the limit, or
    the first ones in line otherwise (a preview); `freed_bytes` is what they add up to."""

    policy: Policy
    total_bytes: int
    over: bool
    candidates: tuple[Candidate, ...]

    @property
    def target_bytes(self) -> int | None:
        if self.policy.max_bytes is None:
            return None
        return int(self.policy.max_bytes * LOW_WATER)

    @property
    def freed_bytes(self) -> int:
        return sum(c.size_bytes for c in self.candidates)

    @property
    def reachable(self) -> bool:
        """False when the unprotected tracks are not enough to get under the target."""
        target = self.target_bytes
        return target is None or not self.over or self.total_bytes - self.freed_bytes <= target


@dataclass(frozen=True)
class RunResult:
    tracks: int
    bytes: int
    reached: bool
    files_left: int = 0


# ---------------------------------------------------------------------- settings


def _setting(conn: Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def _put(conn: Connection, key: str, value: str, now: str) -> None:
    if conn.execute(
        "UPDATE settings SET value = ?, updated_at = ? WHERE key = ?", (value, now, key)
    ).rowcount:
        return
    conn.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)", (key, value, now)
    )


def read_policy(conn: Connection) -> Policy:
    """The stored limit; anything unreadable counts as off (never frees by mistake)."""
    raw_max, raw_grace = _setting(conn, KEY_MAX_BYTES), _setting(conn, KEY_GRACE_DAYS)
    try:
        max_bytes = int(raw_max) if raw_max else None
    except ValueError:
        max_bytes = None
    try:
        grace = int(raw_grace) if raw_grace else DEFAULT_GRACE_DAYS
    except ValueError:
        grace = DEFAULT_GRACE_DAYS
    if max_bytes is not None and max_bytes <= 0:
        max_bytes = None
    return Policy(max_bytes, min(max(grace, 0), MAX_GRACE_DAYS))


def save_policy(conn: Connection, policy: Policy, now: str) -> None:
    if policy.max_bytes is None:
        conn.execute("DELETE FROM settings WHERE key = ?", (KEY_MAX_BYTES,))
    else:
        _put(conn, KEY_MAX_BYTES, str(policy.max_bytes), now)
    _put(conn, KEY_GRACE_DAYS, str(policy.grace_days), now)


def last_run(conn: Connection) -> dict[str, object] | None:
    raw = _setting(conn, KEY_LAST_RUN)
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


# ---------------------------------------------------------------------- planning


def library_bytes(conn: Connection) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(size_bytes), 0) AS n FROM tracks WHERE status = 'ready'"
    ).fetchone()
    if row is None:  # pragma: no cover - an aggregate always returns one row
        return 0
    return int(str(row["n"]))


def _cutoff(clock: Clock, policy: Policy) -> str:
    return format_ts(clock.now() - timedelta(days=policy.grace_days))


def plan(conn: Connection, clock: Clock, policy: Policy, *, preview: int = 10) -> Plan:
    """Over the limit: every track to free, in order. Otherwise the next `preview` in line."""
    total = library_bytes(conn)
    over = policy.max_bytes is not None and total > policy.max_bytes
    cursor = conn.execute(_CANDIDATES, (_cutoff(clock, policy),))
    picked: list[Candidate] = []
    need = total - int(policy.max_bytes * LOW_WATER) if over and policy.max_bytes else 0
    freed = 0
    for row in cursor.fetchall():
        if over and freed >= need:
            break
        if not over and len(picked) >= preview:
            break
        candidate = Candidate(
            track_id=str(row["id"]),
            title=str(row["title"]),
            artist=str(row["artist_name"]),
            path=str(row["path"]),
            size_bytes=int(str(row["size_bytes"])),
            plays=int(str(row["plays"])),
            last_played=str(row["last_played"]) or None,
        )
        picked.append(candidate)
        freed += candidate.size_bytes
    return Plan(policy, total, over, tuple(picked))


# ---------------------------------------------------------------------- freeing


class Evictor:
    def __init__(self, db: Database, library: LibraryStore, clock: Clock) -> None:
        self._db = db
        self._library = library
        self._clock = clock

    def plan(self, *, preview: int = 10) -> Plan:
        with self._db.read() as conn:
            return plan(conn, self._clock, read_policy(conn), preview=preview)

    def run_once(self) -> RunResult:
        current = self.plan()
        if not current.over:
            return RunResult(0, 0, reached=True)
        cutoff = _cutoff(self._clock, current.policy)
        tracks = freed = left = 0
        for candidate in current.candidates:
            if not self._free(candidate, cutoff):
                continue
            tracks += 1
            freed += candidate.size_bytes
            try:
                self._library.delete(candidate.path)
            except (OSError, PathRejected) as exc:
                left += 1
                log.warning(
                    "library limit: the file of track %s was left on disk (%s)",
                    candidate.track_id,
                    type(exc).__name__,
                )
        result = RunResult(tracks, freed, reached=current.reachable, files_left=left)
        self._record(current, result)
        return result

    def _free(self, candidate: Candidate, cutoff: str) -> bool:
        now = format_ts(self._clock.now())
        with self._db.transaction() as conn:
            changed = conn.execute(
                _FREE,
                (now, candidate.track_id, candidate.path, candidate.track_id, cutoff),
            ).rowcount
            if changed != 1:
                # Starred, re-downloaded or freed meanwhile, or a download started.
                return False
            # A `ready` job row would make the next play reuse it instead of downloading.
            conn.execute(
                "DELETE FROM jobs WHERE kind = 'download' AND track_id = ?"
                " AND state NOT IN ('downloading', 'tagging')",
                (candidate.track_id,),
            )
        return True

    def _record(self, current: Plan, result: RunResult) -> None:
        now = format_ts(self._clock.now())
        detail = {"tracks": result.tracks, "bytes": result.bytes, "reached": result.reached}
        with self._db.transaction() as conn:
            _put(conn, KEY_LAST_RUN, json.dumps({"at": now, **detail}, sort_keys=True), now)
            if result.tracks:
                AuditRepository(conn).add(
                    AuditEntry(
                        id=new_id(self._clock),
                        occurred_at=now,
                        actor_user_id=None,
                        actor_ip=None,
                        action="library.evict",
                        target_type=None,
                        target_id=None,
                        detail=json.dumps(detail, sort_keys=True),
                    )
                )
        if result.tracks:
            log.info(
                "library limit: freed %d tracks (%d bytes); the library had %d of %d bytes",
                result.tracks,
                result.bytes,
                current.total_bytes,
                current.policy.max_bytes or 0,
            )
        if not result.reached:
            log.warning(
                "library limit: still over %d bytes; only protected tracks are left to free",
                current.policy.max_bytes or 0,
            )

    async def run_forever(self, interval_s: float) -> None:
        while True:
            await anyio.sleep(interval_s)
            try:
                await run_in_threadpool(self.run_once)
            except Exception:
                log.exception("library limit check failed")
