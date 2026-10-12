# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The `lyrics` table (one row per track, 0001_init.sql) and the track lookup lyrics need.

`resolve_song` follows contracts/ids.md for the ids `getLyricsBySongId` accepts: a library
UUID (lowercased first; a `merged` track resolves to its `merged_into` track, one hop) or a
`yt:` id through `track_aliases`. A `yt:` id without an alias is an external song, which has
no `tracks` row and therefore no stored lyrics: `None`.

The shared resolver of virtual ids is PLAN T06's (`ultimatetunes/ids/`). Until it lands, this
module carries the few lines lyrics need; switch to it once it exists.
"""

import re
from dataclasses import dataclass

from ultimatetunes.db.repository import Repository, to_db_bool
from ultimatetunes.errors import InvalidId, NotFound

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
YT_PREFIX = "yt:"


@dataclass(frozen=True)
class LyricsTrack:
    id: str
    status: str
    title: str
    artist_name: str
    album_name: str | None
    duration_ms: int | None
    merged_into: str | None


@dataclass(frozen=True)
class StoredLyrics:
    track_id: str
    source: str
    source_ref: str | None
    lang: str
    synced_lrc: str | None
    plain_text: str | None
    offset_ms: int
    not_found: bool
    fetched_at: str
    retry_after: str | None


_TRACK_SQL = (
    "SELECT id, status, title, artist_name, album_name, duration_ms, merged_into"
    " FROM tracks WHERE id = ?"
)
_LYRICS_SQL = (
    "SELECT track_id, source, source_ref, lang, synced_lrc, plain_text, offset_ms, not_found,"
    " fetched_at, retry_after FROM lyrics WHERE track_id = ?"
)


class LyricsRepository(Repository):
    def track(self, track_id: str) -> LyricsTrack | None:
        return self.one(LyricsTrack, _TRACK_SQL, (track_id,))

    def resolve_song(self, song_id: str) -> LyricsTrack | None:
        """The library track of `song_id`, `None` for an external `yt:` song. Raises `InvalidId`
        for anything that is not a song id and `NotFound` for an unknown library id."""
        if song_id.startswith(YT_PREFIX):
            video_id = song_id[len(YT_PREFIX) :]
            if not _VIDEO_ID.match(video_id):
                raise InvalidId("Invalid song id")
            target = self.conn.execute(
                "SELECT track_id FROM track_aliases WHERE alias = ?", (song_id,)
            ).scalar()
            if target is None:
                return None
            track_id = str(target)
        else:
            track_id = song_id.lower()
            if not _UUID.match(track_id):
                raise InvalidId("Invalid song id")
        track = self.track(track_id)
        if track is not None and track.status == "merged" and track.merged_into:
            track = self.track(track.merged_into)
        if track is None:
            raise NotFound("Song not found")
        return track

    def lyrics(self, track_id: str) -> StoredLyrics | None:
        return self.one(StoredLyrics, _LYRICS_SQL, (track_id,))

    def save(self, lyrics: StoredLyrics) -> None:
        """Inserts or replaces the row of `lyrics.track_id`."""
        self.run(
            "INSERT INTO lyrics (track_id, source, source_ref, lang, synced_lrc, plain_text,"
            " offset_ms, not_found, fetched_at, retry_after)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (track_id) DO UPDATE SET source = excluded.source,"
            " source_ref = excluded.source_ref, lang = excluded.lang,"
            " synced_lrc = excluded.synced_lrc, plain_text = excluded.plain_text,"
            " offset_ms = excluded.offset_ms, not_found = excluded.not_found,"
            " fetched_at = excluded.fetched_at, retry_after = excluded.retry_after",
            (
                lyrics.track_id,
                lyrics.source,
                lyrics.source_ref,
                lyrics.lang,
                lyrics.synced_lrc,
                lyrics.plain_text,
                lyrics.offset_ms,
                to_db_bool(lyrics.not_found),
                lyrics.fetched_at,
                lyrics.retry_after,
            ),
        )
