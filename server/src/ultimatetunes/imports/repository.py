# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""SQL of the imports: `imports`, `import_items`, and the user playlist an import ends in.

Portable SQL only (contracts/db/README.md). Counters on `imports` are recomputed from the items
in the same statement that records an item, so they never drift from the match report. The
playlist is written once, in the transaction that marks the import `done`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from ultimatetunes.db.repository import Repository
from ultimatetunes.imports.files import SourceItem

ImportSource = Literal["ytmusic", "csv", "exportify_csv", "spotify_json"]
ImportState = Literal["queued", "reading", "matching", "done", "failed"]
ItemState = Literal["pending", "matched", "not_found", "failed"]
TERMINAL: tuple[ImportState, ...] = ("done", "failed")
ACTIVE: tuple[ImportState, ...] = ("queued", "reading", "matching")
DEFAULT_PLAYLIST_NAME = "Imported playlist"
# SQLite allows 999 host parameters in old builds; stay well below.
_CHUNK = 500


@dataclass(frozen=True)
class ImportRow:
    id: str
    user_id: str
    source: str
    source_url: str | None
    source_playlist_id: str | None
    name: str | None
    state: str
    total_items: int
    matched_items: int
    not_found_items: int
    playlist_id: str | None
    error_code: str | None
    error_message: str | None
    created_at: str
    updated_at: str
    finished_at: str | None
    done_items: int


@dataclass(frozen=True)
class ItemRow:
    position: int
    source_ref: str | None
    source_title: str
    source_artist: str | None
    source_album: str | None
    source_duration_ms: int | None
    source_isrc: str | None
    state: str
    match_score: float | None
    yt_video_id: str | None
    track_id: str | None
    error_message: str | None

    def source(self) -> SourceItem:
        artists = tuple(a.strip() for a in (self.source_artist or "").split(";") if a.strip())
        duration = None if self.source_duration_ms is None else self.source_duration_ms // 1000
        return SourceItem(
            self.source_title,
            artists,
            self.source_album,
            duration,
            self.source_isrc,
            self.source_ref,
            self.yt_video_id,
        )


@dataclass(frozen=True)
class TrackRow:
    """What an `ImportItem.track` shows of a library track (merged ones are followed)."""

    id: str
    status: str
    title: str
    artist_name: str
    artist_id: str | None
    album_name: str | None
    album_id: str | None
    duration_ms: int | None
    year: int | None
    yt_video_id: str | None
    yt_album_browse_id: str | None
    yt_artist_channel_id: str | None
    merged_into: str | None


_IMPORT_COLUMNS = (
    "id, user_id, source, source_url, source_playlist_id, name, state, total_items,"
    " matched_items, not_found_items, playlist_id, error_code, error_message, created_at,"
    " updated_at, finished_at,"
    " (SELECT COUNT(*) FROM import_items i WHERE i.import_id = imports.id"
    " AND i.state <> 'pending') AS done_items"
)
_ITEM_COLUMNS = (
    "position, source_ref, source_title, source_artist, source_album, source_duration_ms,"
    " source_isrc, state, match_score, yt_video_id, track_id, error_message"
)
_TRACK_COLUMNS = (
    "id, status, title, artist_name, artist_id, album_name, album_id, duration_ms, year,"
    " yt_video_id, yt_album_browse_id, yt_artist_channel_id, merged_into"
)
_COUNTERS = (
    "matched_items = (SELECT COUNT(*) FROM import_items i WHERE i.import_id = ?"
    " AND i.state = 'matched'),"
    " not_found_items = (SELECT COUNT(*) FROM import_items i WHERE i.import_id = ?"
    " AND i.state = 'not_found')"
)


def _in(count: int) -> str:
    """`(?, ?, ...)`: only placeholders are ever added to the SQL text."""
    return "(" + ", ".join("?" * count) + ")"


class ImportRepository(Repository):
    def create(  # noqa: PLR0913 - the columns of a new import
        self,
        *,
        import_id: str,
        user_id: str,
        source: ImportSource,
        source_url: str | None,
        source_playlist_id: str | None,
        name: str | None,
        now: str,
    ) -> None:
        self.run(
            "INSERT INTO imports (id, user_id, source, source_url, source_playlist_id, name,"
            " state, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?)",
            (import_id, user_id, source, source_url, source_playlist_id, name, now, now),
        )

    def add_items(self, import_id: str, items: Sequence[SourceItem], now: str) -> None:
        """Inserts the source tracks (positions from 0) and sets the total."""
        for position, item in enumerate(items):
            self.run(
                "INSERT INTO import_items (import_id, position, source_ref, source_title,"
                " source_artist, source_album, source_duration_ms, source_isrc, state,"
                " yt_video_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                (
                    import_id,
                    position,
                    item.ref,
                    item.title,
                    item.artist_text,
                    item.album,
                    None if item.duration_s is None else item.duration_s * 1000,
                    item.isrc,
                    item.video_id,
                ),
            )
        self.run(
            "UPDATE imports SET total_items = ?, updated_at = ? WHERE id = ?",
            (len(items), now, import_id),
        )

    def get(self, import_id: str, user_id: str | None = None) -> ImportRow | None:
        if user_id is None:
            return self.one(
                ImportRow,
                f"SELECT {_IMPORT_COLUMNS} FROM imports WHERE id = ?",  # noqa: S608  # nosec B608
                (import_id,),
            )
        return self.one(
            ImportRow,
            f"SELECT {_IMPORT_COLUMNS} FROM imports WHERE id = ? AND user_id = ?",  # noqa: S608  # nosec B608
            (import_id, user_id),
        )

    def list_for(self, user_id: str, limit: int, offset: int) -> list[ImportRow]:
        return self.all(
            ImportRow,
            f"SELECT {_IMPORT_COLUMNS} FROM imports WHERE user_id = ?"  # noqa: S608  # nosec B608
            " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset),
        )

    def active_ids(self, user_id: str) -> list[tuple[str, str]]:
        """(id, updated_at) of the user's imports still running."""
        rows = self.conn.execute(
            "SELECT id, updated_at FROM imports WHERE user_id = ? AND state IN"
            " ('queued', 'reading', 'matching') ORDER BY created_at",
            (user_id,),
        ).fetchall()
        return [(str(r["id"]), str(r["updated_at"])) for r in rows]

    def set_state(self, import_id: str, state: ImportState, now: str) -> None:
        self.run(
            "UPDATE imports SET state = ?, updated_at = ? WHERE id = ?", (state, now, import_id)
        )

    def set_default_name(self, import_id: str, name: str | None, now: str) -> None:
        self.run(
            "UPDATE imports SET name = COALESCE(name, ?), updated_at = ? WHERE id = ?",
            (name, now, import_id),
        )

    def items(self, import_id: str) -> list[ItemRow]:
        return self.all(
            ItemRow,
            f"SELECT {_ITEM_COLUMNS} FROM import_items WHERE import_id = ?"  # noqa: S608  # nosec B608
            " ORDER BY position",
            (import_id,),
        )

    def pending_items(self, import_id: str) -> list[ItemRow]:
        return self.all(
            ItemRow,
            f"SELECT {_ITEM_COLUMNS} FROM import_items WHERE import_id = ?"  # noqa: S608  # nosec B608
            " AND state = 'pending' ORDER BY position",
            (import_id,),
        )

    def record_item(  # noqa: PLR0913 - the outcome of one item
        self,
        import_id: str,
        position: int,
        *,
        state: ItemState,
        now: str,
        score: float | None = None,
        video_id: str | None = None,
        track_id: str | None = None,
        error: str | None = None,
    ) -> None:
        self.run(
            "UPDATE import_items SET state = ?, match_score = ?,"
            " yt_video_id = COALESCE(?, yt_video_id), track_id = ?, error_message = ?"
            " WHERE import_id = ? AND position = ?",
            (state, score, video_id, track_id, error, import_id, position),
        )
        self.run(
            f"UPDATE imports SET {_COUNTERS}, updated_at = ? WHERE id = ?",  # noqa: S608  # nosec B608
            (import_id, import_id, now, import_id),
        )

    def finish(self, import_id: str, playlist_id: str, now: str) -> bool:
        """Ends an active import as `done` and creates its user playlist from the matched
        items, in source order. Call it inside one transaction. The state change is a
        conditional update checked by row count, so two runs (or a run and a `fail`) never
        create two playlists; False when the import was not active."""
        ended = self.run(
            "UPDATE imports SET state = 'done', updated_at = ?, finished_at = ?"
            " WHERE id = ? AND state IN ('queued', 'reading', 'matching')",
            (now, now, import_id),
        )
        row = self.get(import_id) if ended == 1 else None
        if row is None:
            return False
        self.run(
            "INSERT INTO playlists (id, owner_id, name, comment, is_public, created_at,"
            " updated_at) VALUES (?, ?, ?, ?, 0, ?, ?)",
            (playlist_id, row.user_id, row.name or DEFAULT_PLAYLIST_NAME, "Imported", now, now),
        )
        tracks = self.conn.execute(
            "SELECT track_id FROM import_items WHERE import_id = ? AND state = 'matched'"
            " AND track_id IS NOT NULL ORDER BY position",
            (import_id,),
        ).fetchall()
        for position, track in enumerate(tracks):
            self.run(
                "INSERT INTO playlist_tracks (playlist_id, position, track_id, added_at)"
                " VALUES (?, ?, ?, ?)",
                (playlist_id, position, track["track_id"], now),
            )
        self.run("UPDATE imports SET playlist_id = ? WHERE id = ?", (playlist_id, import_id))
        return True

    def fail(self, import_id: str, code: str, message: str, now: str) -> bool:
        """Ends an active import as `failed`; never touches one that already ended."""
        failed = self.run(
            "UPDATE imports SET state = 'failed', error_code = ?, error_message = ?,"
            " updated_at = ?, finished_at = ? WHERE id = ?"
            " AND state IN ('queued', 'reading', 'matching')",
            (code, message, now, now, import_id),
        )
        return failed == 1

    def _fetch(self, track_ids: Sequence[str]) -> dict[str, TrackRow]:
        found: dict[str, TrackRow] = {}
        distinct = list(dict.fromkeys(track_ids))
        for start in range(0, len(distinct), _CHUNK):
            chunk = distinct[start : start + _CHUNK]
            rows = self.all(
                TrackRow,
                f"SELECT {_TRACK_COLUMNS} FROM tracks WHERE id IN {_in(len(chunk))}",  # noqa: S608  # nosec B608
                chunk,
            )
            found.update((r.id, r) for r in rows)
        return found

    def tracks(self, track_ids: Sequence[str]) -> dict[str, TrackRow]:
        """Library tracks by id; a merged track shows the one it was merged into (one hop)."""
        found = self._fetch(track_ids)
        merged = {k: v.merged_into for k, v in found.items() if v.status == "merged"}
        targets = self._fetch([t for t in merged.values() if t])
        for source, target in merged.items():
            follow = targets.get(target) if target else None
            if follow is None or follow.status == "merged":
                del found[source]
            else:
                found[source] = follow
        return found
