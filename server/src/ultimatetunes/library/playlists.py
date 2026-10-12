# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""User playlists (RF-09).

A user sees their own playlists and other users' public ones (`readonly`). Only the owner
changes or deletes a playlist: someone else's public playlist answers `Forbidden`, a private
one `NotFound` (its existence is not revealed). Adding songs is a "keep" action: `yt:` ids are
materialized and their downloads requested (`library.songs.keep`), and every id is checked
before anything is written. Entries are rewritten by deleting them and inserting the new list
in one transaction (positions are part of the key, contracts/db/README.md).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from starlette.concurrency import run_in_threadpool

from ultimatetunes.core.clock import format_ts
from ultimatetunes.db.driver import Connection
from ultimatetunes.db.repository import Repository
from ultimatetunes.errors import Forbidden, InvalidParameter, NotFound, PayloadTooLarge
from ultimatetunes.ids.uuid7 import new_id
from ultimatetunes.ids.virtual import LibraryId, cover_id, parse_id
from ultimatetunes.library.render import Obj, compact, seconds
from ultimatetunes.library.songs import children, keep

if TYPE_CHECKING:
    from ultimatetunes.core.services import Services

MAX_NAME = 200
MAX_COMMENT = 2000
MAX_TRACKS = 10000


@dataclass(frozen=True)
class PlaylistRow:
    id: str
    owner_id: str
    owner_name: str
    name: str
    comment: str | None
    is_public: bool
    created_at: str
    updated_at: str
    song_count: int
    duration_ms: int


_SELECT = (
    "SELECT p.id, p.owner_id, u.username AS owner_name, p.name, p.comment, p.is_public,"
    " p.created_at, p.updated_at, COUNT(e.track_id) AS song_count,"
    " COALESCE(SUM(t.duration_ms), 0) AS duration_ms"
    " FROM playlists p JOIN users u ON u.id = p.owner_id"
    " LEFT JOIN playlist_tracks e ON e.playlist_id = p.id"
    " LEFT JOIN tracks t ON t.id = e.track_id"
)
_GROUP = (
    " GROUP BY p.id, p.owner_id, u.username, p.name, p.comment, p.is_public, p.created_at,"
    " p.updated_at"
)


class _Repo(Repository):
    def visible(self, user_id: str) -> list[PlaylistRow]:
        sql = (
            _SELECT + " WHERE p.owner_id = ? OR p.is_public = 1" + _GROUP + " ORDER BY p.name, p.id"
        )
        return self.all(PlaylistRow, sql, (user_id,))

    def by_id(self, playlist_id: str) -> PlaylistRow | None:
        return self.one(PlaylistRow, _SELECT + " WHERE p.id = ?" + _GROUP, (playlist_id,))

    def entries(self, playlist_id: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT track_id FROM playlist_tracks WHERE playlist_id = ? ORDER BY position",
            (playlist_id,),
        ).fetchall()
        return [str(r["track_id"]) for r in rows]


def _playlist_id(raw: str) -> str:
    parsed = parse_id(raw)
    if not isinstance(parsed, LibraryId):
        raise NotFound("Playlist not found")
    return parsed.value


def check_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned or len(cleaned) > MAX_NAME:
        raise InvalidParameter(f"name must be 1 to {MAX_NAME} characters")
    return cleaned


def payload(row: PlaylistRow, user_id: str) -> Obj:
    return compact(
        {
            "id": row.id,
            "name": row.name,
            "comment": row.comment,
            "owner": row.owner_name,
            "public": row.is_public,
            "songCount": row.song_count,
            "duration": seconds(row.duration_ms) or 0,
            "created": row.created_at,
            "changed": row.updated_at,
            "coverArt": cover_id("playlist", row.id),
            "readonly": row.owner_id != user_id,
        }
    )


class Playlists:
    def __init__(self, services: "Services", user_id: str) -> None:
        self._services = services
        self._user = user_id

    def _now(self) -> str:
        return format_ts(self._services.clock.now())

    # ------------------------------------------------------------------ reads

    def visible(self) -> list[Obj]:
        with self._services.db.read() as conn:
            rows = _Repo(conn).visible(self._user)
        return [payload(r, self._user) for r in rows]

    def _visible_row(self, conn: Connection, playlist_id: str) -> PlaylistRow:
        row = _Repo(conn).by_id(playlist_id)
        if row is None or (row.owner_id != self._user and not row.is_public):
            raise NotFound("Playlist not found")
        return row

    def _owned_row(self, conn: Connection, playlist_id: str) -> PlaylistRow:
        row = self._visible_row(conn, playlist_id)
        if row.owner_id != self._user:
            raise Forbidden("Only the owner can change a playlist")
        return row

    def _read(self, playlist_id: str) -> tuple[PlaylistRow, list[str]]:
        with self._services.db.read() as conn:
            row = self._visible_row(conn, playlist_id)
            return row, _Repo(conn).entries(playlist_id)

    async def with_songs(self, raw_id: str) -> Obj:
        row, entries = await run_in_threadpool(self._read, _playlist_id(raw_id))
        songs = await children(self._services, self._user, entries)
        return {**payload(row, self._user), "entry": songs}

    def _require_owned(self, playlist_id: str) -> None:
        with self._services.db.read() as conn:
            self._owned_row(conn, playlist_id)

    # ------------------------------------------------------------------ writes

    def _write(  # noqa: PLR0913 - the fields one write may change
        self,
        playlist_id: str | None,
        *,
        name: str | None = None,
        comment: str | None = None,
        public: bool | None = None,
        tracks: Sequence[str] | None = None,
        add: Sequence[str] = (),
        remove: Sequence[int] = (),
    ) -> str:
        now = self._now()
        with self._services.db.transaction() as conn:
            if playlist_id is None:
                playlist_id = new_id(self._services.clock)
                conn.execute(
                    "INSERT INTO playlists (id, owner_id, name, is_public, created_at,"
                    " updated_at) VALUES (?, ?, ?, 0, ?, ?)",
                    (playlist_id, self._user, name, now, now),
                )
                current: list[str] = []
            else:
                self._owned_row(conn, playlist_id)
                current = _Repo(conn).entries(playlist_id)
            new = list(current if tracks is None else tracks)
            if remove:
                if any(i < 0 or i >= len(new) for i in remove):
                    raise InvalidParameter("songIndexToRemove is out of range")
                dropped = set(remove)
                new = [t for i, t in enumerate(new) if i not in dropped]
            new += add
            if len(new) > MAX_TRACKS:
                raise PayloadTooLarge(f"A playlist holds at most {MAX_TRACKS} songs")
            if new != current:
                conn.execute("DELETE FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,))
                for position, track in enumerate(new):
                    conn.execute(
                        "INSERT INTO playlist_tracks (playlist_id, position, track_id, added_at)"
                        " VALUES (?, ?, ?, ?)",
                        (playlist_id, position, track, now),
                    )
            updates: list[tuple[str, object]] = [("updated_at", now)]
            if name is not None:
                updates.append(("name", name))
            if comment is not None:
                updates.append(("comment", comment))
            if public is not None:
                updates.append(("is_public", 1 if public else 0))
            # Only the fixed column names above are joined into the SQL text.
            assignments = ", ".join(f"{column} = ?" for column, _ in updates)
            conn.execute(
                f"UPDATE playlists SET {assignments} WHERE id = ?",  # noqa: S608  # nosec B608
                (*(value for _, value in updates), playlist_id),
            )
        return playlist_id

    async def create(self, name: str | None, playlist: str | None, songs: Sequence[str]) -> Obj:
        """`createPlaylist`: a new playlist, or (with `playlist`) new songs for an existing one."""
        target = _playlist_id(playlist) if playlist else None
        if target is None and not name:
            raise InvalidParameter("name is required to create a playlist")
        clean_name = check_name(name) if name else None
        if target is not None:
            await run_in_threadpool(self._require_owned, target)
        tracks = await keep(self._services, self._user, songs)
        playlist_id = await run_in_threadpool(
            lambda: self._write(target, name=clean_name, tracks=tracks)
        )
        return await self.with_songs(playlist_id)

    async def update(  # noqa: PLR0913 - the parameters of updatePlaylist
        self,
        playlist: str,
        *,
        name: str | None,
        comment: str | None,
        public: bool | None,
        add: Sequence[str],
        remove: Sequence[int],
    ) -> None:
        target = _playlist_id(playlist)
        clean_name = check_name(name) if name is not None else None
        if comment is not None and len(comment) > MAX_COMMENT:
            raise InvalidParameter(f"comment must be at most {MAX_COMMENT} characters")
        await run_in_threadpool(self._require_owned, target)
        tracks = await keep(self._services, self._user, add)
        await run_in_threadpool(
            lambda: self._write(
                target, name=clean_name, comment=comment, public=public, add=tracks, remove=remove
            )
        )

    def delete(self, playlist: str) -> None:
        target = _playlist_id(playlist)
        with self._services.db.transaction() as conn:
            self._owned_row(conn, target)
            conn.execute("DELETE FROM playlists WHERE id = ?", (target,))
