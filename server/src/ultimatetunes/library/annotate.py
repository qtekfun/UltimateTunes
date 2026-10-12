# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-user favourites and play history (RF-09): stars and scrobbles.

Starring a `yt:` song is a "keep" action: it materializes the song and requests its download
(`library.songs.keep`). Starring `ytalbum:` / `ytartist:` ids is not supported in v1
(error 0, contracts/ids.md). Unstarring never materializes anything: a `yt:` id without a
library track has no star to remove. A plain `id` that is a library album or artist UUID
stars that album or artist (older Subsonic clients send them that way).

A played scrobble (`submission` true) is also a "keep" action. It adds a `play_history` row
and counts in `user_track_stats`; a "now playing" notification (`submission` false) is kept in
the history with `submission = 0` and counts nothing.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from starlette.concurrency import run_in_threadpool

from ultimatetunes.core.clock import format_ts
from ultimatetunes.db.driver import Connection
from ultimatetunes.errors import InvalidParameter, NotFound
from ultimatetunes.ids.resolve import TrackRef, resolve_track
from ultimatetunes.ids.uuid7 import new_id
from ultimatetunes.ids.virtual import VirtualId, parse_id
from ultimatetunes.library.repository import LibraryRepository
from ultimatetunes.library.songs import check_count, keep

if TYPE_CHECKING:
    from ultimatetunes.core.services import Services

Kind = Literal["song", "album", "artist"]
MAX_CLIENT = 64
_TABLES = {
    "song": ("starred_tracks", "track_id"),
    "album": ("starred_albums", "album_id"),
    "artist": ("starred_artists", "artist_id"),
}


@dataclass
class Targets:
    """Ids of a star/unstar request, by kind (songs keep their raw form)."""

    songs: list[str] = field(default_factory=list)
    albums: list[str] = field(default_factory=list)
    artists: list[str] = field(default_factory=list)


def _library_only(raw: str, kind: str) -> str:
    parsed = parse_id(raw)
    if isinstance(parsed, VirtualId):
        raise InvalidParameter(f"Request the {kind} first: external {kind}s cannot be starred")
    return parsed.value


def _classify(
    conn: Connection, ids: Sequence[str], albums: Sequence[str], artists: Sequence[str]
) -> Targets:
    repo = LibraryRepository(conn)
    targets = Targets()
    for raw in ids:
        parsed = parse_id(raw)
        if isinstance(parsed, VirtualId):
            if parsed.kind != "song":
                raise InvalidParameter(
                    "Request it first: external albums and artists cannot be starred"
                )
            targets.songs.append(raw)
        elif repo.exists("tracks", parsed.value):
            targets.songs.append(parsed.value)
        elif repo.exists("albums", parsed.value):
            targets.albums.append(parsed.value)
        elif repo.exists("artists", parsed.value):
            targets.artists.append(parsed.value)
        else:
            raise NotFound("Song not found")
    for raw in albums:
        value = _library_only(raw, "album")
        if not repo.exists("albums", value):
            raise NotFound("Album not found")
        targets.albums.append(value)
    for raw in artists:
        value = _library_only(raw, "artist")
        if not repo.exists("artists", value):
            raise NotFound("Artist not found")
        targets.artists.append(value)
    return targets


class Annotations:
    def __init__(self, services: "Services", user_id: str) -> None:
        self._services = services
        self._user = user_id

    def _now(self) -> str:
        return format_ts(self._services.clock.now())

    def _targets(
        self, ids: Sequence[str], albums: Sequence[str], artists: Sequence[str]
    ) -> Targets:
        check_count([*ids, *albums, *artists])
        with self._services.db.read() as conn:
            return _classify(conn, ids, albums, artists)

    def _write_stars(self, kind: Kind, ids: Sequence[str], *, add: bool) -> None:
        table, column = _TABLES[kind]
        now = self._now()
        with self._services.db.transaction() as conn:
            for value in dict.fromkeys(ids):
                if add:
                    conn.execute(
                        f"INSERT INTO {table} (user_id, {column}, starred_at) VALUES (?, ?, ?)"  # noqa: S608  # nosec B608
                        f" ON CONFLICT (user_id, {column}) DO NOTHING",
                        (self._user, value, now),
                    )
                else:
                    conn.execute(
                        f"DELETE FROM {table} WHERE user_id = ? AND {column} = ?",  # noqa: S608  # nosec B608
                        (self._user, value),
                    )

    async def star(self, ids: Sequence[str], albums: Sequence[str], artists: Sequence[str]) -> None:
        targets = await run_in_threadpool(self._targets, ids, albums, artists)
        tracks = await keep(self._services, self._user, targets.songs)
        await run_in_threadpool(self._write_stars, "song", tracks, add=True)
        await run_in_threadpool(self._write_stars, "album", targets.albums, add=True)
        await run_in_threadpool(self._write_stars, "artist", targets.artists, add=True)

    def _known_tracks(self, songs: Sequence[str]) -> list[str]:
        found: list[str] = []
        with self._services.db.read() as conn:
            for raw in songs:
                target = resolve_track(conn, raw)
                if isinstance(target, TrackRef):
                    found.append(target.id)
        return found

    def unstar(self, ids: Sequence[str], albums: Sequence[str], artists: Sequence[str]) -> None:
        targets = self._targets(ids, albums, artists)
        self._write_stars("song", self._known_tracks(targets.songs), add=False)
        self._write_stars("album", targets.albums, add=False)
        self._write_stars("artist", targets.artists, add=False)

    # ------------------------------------------------------------------ scrobble

    def _record(
        self, tracks: Sequence[str], times: Sequence[str], *, submission: bool, client: str | None
    ) -> None:
        with self._services.db.transaction() as conn:
            for track, played_at in zip(tracks, times, strict=True):
                conn.execute(
                    "INSERT INTO play_history (id, user_id, track_id, played_at, submission,"
                    " client) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        new_id(self._services.clock),
                        self._user,
                        track,
                        played_at,
                        1 if submission else 0,
                        client,
                    ),
                )
                if not submission:
                    continue
                conn.execute(
                    "INSERT INTO user_track_stats (user_id, track_id, play_count, last_played_at)"
                    " VALUES (?, ?, 1, ?) ON CONFLICT (user_id, track_id) DO UPDATE SET"
                    " play_count = user_track_stats.play_count + 1,"
                    " last_played_at = CASE WHEN user_track_stats.last_played_at IS NULL"
                    " OR user_track_stats.last_played_at < excluded.last_played_at"
                    " THEN excluded.last_played_at ELSE user_track_stats.last_played_at END",
                    (self._user, track, played_at),
                )

    def _played_times(self, ids: Sequence[str], times: Sequence[str]) -> list[str]:
        if not times:
            return [self._now()] * len(ids)
        if len(times) != len(ids):
            raise InvalidParameter("time must be given once per id")
        out: list[str] = []
        for text in times:
            try:
                moment = datetime.fromtimestamp(int(text) / 1000, UTC)
            except (ValueError, OverflowError, OSError):
                raise InvalidParameter("time must be milliseconds since the epoch") from None
            out.append(format_ts(min(moment, self._services.clock.now())))
        return out

    async def scrobble(
        self, ids: Sequence[str], times: Sequence[str], *, submission: bool, client: str | None
    ) -> None:
        check_count(ids)
        played = self._played_times(ids, times)
        client = client[:MAX_CLIENT] if client else None
        if submission:
            tracks = await keep(self._services, self._user, ids)
            await run_in_threadpool(self._record, tracks, played, submission=True, client=client)
            return
        # Now playing: only songs the library already knows (nothing is materialized).
        pairs = await run_in_threadpool(self._now_playing, ids, played)
        await run_in_threadpool(
            self._record,
            [t for t, _ in pairs],
            [p for _, p in pairs],
            submission=False,
            client=client,
        )

    def _now_playing(self, ids: Sequence[str], played: Sequence[str]) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        with self._services.db.read() as conn:
            for raw, when in zip(ids, played, strict=True):
                target = resolve_track(conn, raw)
                if isinstance(target, TrackRef):
                    out.append((target.id, when))
        return out
