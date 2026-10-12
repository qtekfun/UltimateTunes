# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The `lyrics` table (one row per track, 0001_init.sql) and the track lookup lyrics need.

`resolve_song` resolves the ids `getLyricsBySongId` accepts through `ids.resolve`
(contracts/ids.md): a library UUID (a `merged` track follows `merged_into`) or a `yt:` id with a
library track. A `yt:` id without one is an external song, which has no `tracks` row and
therefore no stored lyrics: `None`.
"""

from dataclasses import dataclass

from ultimatetunes.db.repository import Repository, to_db_bool
from ultimatetunes.errors import NotFound
from ultimatetunes.ids.resolve import resolve_track
from ultimatetunes.ids.virtual import VirtualId


@dataclass(frozen=True)
class LyricsTrack:
    id: str
    title: str
    artist_name: str
    album_name: str | None
    duration_ms: int | None


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


_TRACK_SQL = "SELECT id, title, artist_name, album_name, duration_ms FROM tracks WHERE id = ?"
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
        ref = resolve_track(self.conn, song_id)
        if isinstance(ref, VirtualId):
            return None
        track = self.track(ref.id)
        if track is None:  # deleted between the two reads
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
