# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolution between virtual ids and library rows (contracts/ids.md, "Resolution rules").

- `resolve_track(conn, id)`: a library UUID or a `yt:` id → the library track behind it (a
  merged track resolves to its `merged_into`, one hop), or the external `VirtualId` when a
  `yt:` id has no alias yet.
- `tracks_for_videos`, `albums_for_browse_ids`, `artists_for_channel_ids`: the same lookup in
  bulk, for lists of catalog results (search, radio, album pages) that must show the library
  item instead of its YouTube twin.
- `materialize_song(conn, clock, track)`: the first "keep" action on a `yt:` id creates the
  pending track and its alias (idempotent; the caller enqueues the job in the same transaction).

Every function takes the caller's connection, so it joins the caller's transaction.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, cast

from ultimatetunes.core.clock import Clock, format_ts
from ultimatetunes.db.driver import Connection
from ultimatetunes.errors import NotFound
from ultimatetunes.ids.uuid7 import new_id
from ultimatetunes.ids.virtual import SONG_PREFIX, LibraryId, VirtualId, parse_kind, virtual
from ultimatetunes.search.catalog import CatalogTrack
from ultimatetunes.search.text import normalize

TrackStatus = Literal["pending", "ready", "failed"]

# SQLite allows 999 host parameters in old builds; stay well below.
_CHUNK = 500


@dataclass(frozen=True)
class TrackRef:
    """A library track and its state (`merged` never shows: it is followed)."""

    id: str
    status: TrackStatus


_ALIASES = (
    "SELECT a.alias AS alias, t.id AS id, t.status AS status, t.merged_into AS merged_into"
    " FROM track_aliases a JOIN tracks t ON t.id = a.track_id WHERE a.alias IN "
)
_BY_VIDEO = "SELECT yt_video_id, id, status, merged_into FROM tracks WHERE yt_video_id IN "
_BY_YOUTUBE_ID = {
    "albums": "SELECT yt_browse_id AS yt, id FROM albums WHERE yt_browse_id IN ",
    "artists": "SELECT yt_channel_id AS yt, id FROM artists WHERE yt_channel_id IN ",
}


def _in(count: int) -> str:
    """`(?, ?, ...)`: only placeholders are ever added to the SQL text."""
    return "(" + ", ".join("?" * count) + ")"


def _chunks(values: Sequence[str]) -> list[list[str]]:
    distinct = list(dict.fromkeys(values))
    return [distinct[i : i + _CHUNK] for i in range(0, len(distinct), _CHUNK)]


def _follow(conn: Connection, track_id: str, status: str, merged_into: object) -> TrackRef | None:
    """The track itself, or the one it was merged into (one hop; `merged_into` is never merged)."""
    if status != "merged":
        return TrackRef(track_id, cast("TrackStatus", status))
    if merged_into is None:
        return None
    row = conn.execute("SELECT id, status FROM tracks WHERE id = ?", (merged_into,)).fetchone()
    if row is None or row["status"] == "merged":
        return None
    return TrackRef(str(row["id"]), cast("TrackStatus", row["status"]))


def _track_by_id(conn: Connection, track_id: str) -> TrackRef | None:
    row = conn.execute(
        "SELECT status, merged_into FROM tracks WHERE id = ?", (track_id,)
    ).fetchone()
    if row is None:
        return None
    return _follow(conn, track_id, str(row["status"]), row["merged_into"])


def tracks_for_videos(conn: Connection, video_ids: Sequence[str]) -> dict[str, TrackRef]:
    """Video id → library track, for the videos that have one (alias, else `yt_video_id`)."""
    found: dict[str, TrackRef] = {}
    for chunk in _chunks(video_ids):
        aliases = [SONG_PREFIX + v for v in chunk]
        rows = conn.execute(_ALIASES + _in(len(aliases)), aliases).fetchall()
        for row in rows:
            ref = _follow(conn, str(row["id"]), str(row["status"]), row["merged_into"])
            if ref is not None:
                found[str(row["alias"])[len(SONG_PREFIX) :]] = ref
        missing = [v for v in chunk if v not in found]
        if not missing:
            continue
        rows = conn.execute(_BY_VIDEO + _in(len(missing)), missing).fetchall()
        for row in rows:
            ref = _follow(conn, str(row["id"]), str(row["status"]), row["merged_into"])
            if ref is not None:
                found[str(row["yt_video_id"])] = ref
    return found


def _by_youtube_id(conn: Connection, table: str, ids: Sequence[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    for chunk in _chunks(ids):
        rows = conn.execute(_BY_YOUTUBE_ID[table] + _in(len(chunk)), chunk).fetchall()
        found.update((str(row["yt"]), str(row["id"])) for row in rows)
    return found


def albums_for_browse_ids(conn: Connection, browse_ids: Sequence[str]) -> dict[str, str]:
    """Album browse id → library album id, for the albums the library has."""
    return _by_youtube_id(conn, "albums", browse_ids)


def artists_for_channel_ids(conn: Connection, channel_ids: Sequence[str]) -> dict[str, str]:
    """Artist channel id → library artist id, for the artists the library has."""
    return _by_youtube_id(conn, "artists", channel_ids)


def resolve_track(conn: Connection, raw_id: str) -> TrackRef | VirtualId:
    """A song id → its library track, or the external `yt:` item when it has none.

    `InvalidId` for malformed ids and album or artist ids; `NotFound` for a library UUID that
    does not exist (or was merged into a track that no longer does).
    """
    parsed = parse_kind(raw_id, "song")
    if isinstance(parsed, LibraryId):
        ref = _track_by_id(conn, parsed.value)
        if ref is None:
            raise NotFound("Song not found")
        return ref
    return tracks_for_videos(conn, [parsed.payload]).get(parsed.payload, parsed)


def materialize_song(conn: Connection, clock: Clock, track: CatalogTrack) -> TrackRef:
    """The library track of `track`, created as `pending` with its `yt:` alias if it has none.

    Run it inside the caller's write transaction (`Database.transaction()`), next to the job
    enqueue, so concurrent requests end with one track, one alias and one job.
    """
    video = virtual("song", track.video_id)
    existing = tracks_for_videos(conn, [video.payload]).get(video.payload)
    now = format_ts(clock.now())
    if existing is not None:
        conn.execute(
            "INSERT INTO track_aliases (alias, track_id, created_at) VALUES (?, ?, ?)"
            " ON CONFLICT (alias) DO NOTHING",
            (video.text, existing.id, now),
        )
        return existing
    track_id = new_id(clock)
    artist = track.artists[0] if track.artists else None
    conn.execute(
        "INSERT INTO tracks (id, status, title, title_norm, artist_name, album_name,"
        " track_number, year, duration_ms, yt_video_id, yt_album_browse_id,"
        " yt_artist_channel_id, yt_thumbnail_url, created_at, updated_at)"
        " VALUES (?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            track_id,
            track.title,
            normalize(track.title),
            ", ".join(a.name for a in track.artists),
            track.album.name if track.album else None,
            track.track_number,
            track.year,
            None if track.duration_s is None else track.duration_s * 1000,
            video.payload,
            track.album.browse_id if track.album else None,
            artist.channel_id if artist else None,
            track.thumbnail.url if track.thumbnail else None,
            now,
            now,
        ),
    )
    conn.execute(
        "INSERT INTO track_aliases (alias, track_id, created_at) VALUES (?, ?, ?)",
        (video.text, track_id, now),
    )
    return TrackRef(track_id, "pending")
