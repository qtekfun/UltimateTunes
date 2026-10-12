# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Library side of search: songs, albums and artists matching a query, in portable SQL.

Matching is by words: every word of the normalised query (`text.tokens`) must appear in one
of the item's normalised names (`*_norm`; for a song its title, artist or album). No words
lists the whole library (`search3` with an empty query, used by clients to sync). Only
`ready` tracks count; albums and artists only show when they have one. Per-user fields
(starred, play count, last played) come from the caller's rows.

Only `?` placeholders and constant fragments are ever joined into the SQL text.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from ultimatetunes.db.repository import Repository
from ultimatetunes.search.text import like_pattern

_LIKE = " LIKE ? ESCAPE '\\'"


@dataclass(frozen=True)
class LibrarySong:
    id: str
    title: str
    artist_name: str
    album_name: str | None
    album_id: str | None
    artist_id: str | None
    track_number: int | None
    disc_number: int | None
    year: int | None
    genre: str | None
    duration_ms: int | None
    path: str | None
    format: str | None
    content_type: str | None
    size_bytes: int | None
    bit_rate_kbps: int | None
    sample_rate_hz: int | None
    channels: int | None
    rg_track_gain_db: float | None
    rg_track_peak: float | None
    rg_album_gain_db: float | None
    rg_album_peak: float | None
    musicbrainz_recording_id: str | None
    created_at: str
    album_artist_id: str | None
    album_artist_name: str | None
    starred_at: str | None
    play_count: int | None
    last_played_at: str | None


@dataclass(frozen=True)
class LibraryAlbum:
    id: str
    name: str
    artist_id: str
    artist_name: str
    year: int | None
    genre: str | None
    musicbrainz_release_id: str | None
    created_at: str
    song_count: int
    duration_ms: int
    starred_at: str | None


@dataclass(frozen=True)
class LibraryArtist:
    id: str
    name: str
    sort_name: str | None
    musicbrainz_id: str | None
    album_count: int
    starred_at: str | None


_SONGS = (
    "SELECT t.id, t.title, t.artist_name, t.album_name, t.album_id, t.artist_id,"
    " t.track_number, t.disc_number, t.year, t.genre, t.duration_ms, t.path, t.format,"
    " t.content_type, t.size_bytes, t.bit_rate_kbps, t.sample_rate_hz, t.channels,"
    " t.rg_track_gain_db, t.rg_track_peak, t.rg_album_gain_db, t.rg_album_peak,"
    " t.musicbrainz_recording_id, t.created_at, al.artist_id AS album_artist_id,"
    " aa.name AS album_artist_name, s.starred_at AS starred_at, st.play_count AS play_count,"
    " st.last_played_at AS last_played_at"
    " FROM tracks t"
    " LEFT JOIN artists ar ON ar.id = t.artist_id"
    " LEFT JOIN albums al ON al.id = t.album_id"
    " LEFT JOIN artists aa ON aa.id = al.artist_id"
    " LEFT JOIN starred_tracks s ON s.track_id = t.id AND s.user_id = ?"
    " LEFT JOIN user_track_stats st ON st.track_id = t.id AND st.user_id = ?"
    " WHERE t.status = 'ready'"
)
_SONG_WORD = (
    " AND (t.title_norm" + _LIKE + " OR ar.name_norm" + _LIKE + " OR al.name_norm" + _LIKE + ")"
)
_SONGS_ORDER = " ORDER BY t.title_norm, t.id LIMIT ? OFFSET ?"

_ALBUMS = (
    "SELECT al.id, al.name, al.artist_id, ar.name AS artist_name, al.year, al.genre,"
    " al.musicbrainz_release_id, al.created_at, COUNT(t.id) AS song_count,"
    " COALESCE(SUM(t.duration_ms), 0) AS duration_ms, sa.starred_at AS starred_at"
    " FROM albums al"
    " JOIN artists ar ON ar.id = al.artist_id"
    " JOIN tracks t ON t.album_id = al.id AND t.status = 'ready'"
    " LEFT JOIN starred_albums sa ON sa.album_id = al.id AND sa.user_id = ?"
    " WHERE 1 = 1"
)
_ALBUM_WORD = " AND (al.name_norm" + _LIKE + " OR ar.name_norm" + _LIKE + ")"
_ALBUMS_ORDER = (
    " GROUP BY al.id, al.name, al.name_norm, al.artist_id, ar.name, al.year, al.genre,"
    " al.musicbrainz_release_id, al.created_at, sa.starred_at"
    " ORDER BY al.name_norm, al.id LIMIT ? OFFSET ?"
)

_ARTISTS = (
    "SELECT ar.id, ar.name, ar.sort_name, ar.musicbrainz_id,"
    " COUNT(DISTINCT al.id) AS album_count, sx.starred_at AS starred_at"
    " FROM artists ar"
    " LEFT JOIN albums al ON al.artist_id = ar.id AND EXISTS"
    " (SELECT 1 FROM tracks ta WHERE ta.album_id = al.id AND ta.status = 'ready')"
    " LEFT JOIN starred_artists sx ON sx.artist_id = ar.id AND sx.user_id = ?"
    " WHERE (al.id IS NOT NULL OR EXISTS"
    " (SELECT 1 FROM tracks tr WHERE tr.artist_id = ar.id AND tr.status = 'ready'))"
)
_ARTIST_WORD = " AND ar.name_norm" + _LIKE
_ARTISTS_ORDER = (
    " GROUP BY ar.id, ar.name, ar.name_norm, ar.sort_name, ar.musicbrainz_id, sx.starred_at"
    " ORDER BY ar.name_norm, ar.id LIMIT ? OFFSET ?"
)


def _in(column: str, count: int) -> str:
    return " AND " + column + " IN (" + ", ".join("?" * count) + ")"


class LibrarySearch(Repository):
    def songs(
        self, user_id: str, words: Sequence[str], limit: int, offset: int = 0
    ) -> list[LibrarySong]:
        params: list[object] = [user_id, user_id]
        for word in words:
            params += [like_pattern(word)] * 3
        sql = _SONGS + _SONG_WORD * len(words) + _SONGS_ORDER
        return self.all(LibrarySong, sql, [*params, limit, offset])

    def songs_by_id(self, user_id: str, ids: Sequence[str]) -> list[LibrarySong]:
        if not ids:
            return []
        sql = _SONGS + _in("t.id", len(ids)) + _SONGS_ORDER
        return self.all(LibrarySong, sql, [user_id, user_id, *ids, len(ids), 0])

    def albums(
        self, user_id: str, words: Sequence[str], limit: int, offset: int = 0
    ) -> list[LibraryAlbum]:
        params: list[object] = [user_id]
        for word in words:
            params += [like_pattern(word)] * 2
        sql = _ALBUMS + _ALBUM_WORD * len(words) + _ALBUMS_ORDER
        return self.all(LibraryAlbum, sql, [*params, limit, offset])

    def albums_by_id(self, user_id: str, ids: Sequence[str]) -> list[LibraryAlbum]:
        if not ids:
            return []
        sql = _ALBUMS + _in("al.id", len(ids)) + _ALBUMS_ORDER
        return self.all(LibraryAlbum, sql, [user_id, *ids, len(ids), 0])

    def artists(
        self, user_id: str, words: Sequence[str], limit: int, offset: int = 0
    ) -> list[LibraryArtist]:
        params: list[object] = [user_id, *(like_pattern(w) for w in words)]
        sql = _ARTISTS + _ARTIST_WORD * len(words) + _ARTISTS_ORDER
        return self.all(LibraryArtist, sql, [*params, limit, offset])

    def artists_by_id(self, user_id: str, ids: Sequence[str]) -> list[LibraryArtist]:
        if not ids:
            return []
        sql = _ARTISTS + _in("ar.id", len(ids)) + _ARTISTS_ORDER
        return self.all(LibraryArtist, sql, [user_id, *ids, len(ids), 0])
