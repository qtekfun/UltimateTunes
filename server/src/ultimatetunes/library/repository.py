# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Library reads for browsing (portable SQL, `?` placeholders only).

Only `ready` tracks are library songs; albums and artists show when they have one. Per-user
fields (starred, play count, last played) come from the caller's rows. Songs map to
`search.library.LibrarySong`, so they render exactly like `search3` results
(`search.render.library_child`). Tracks that exist but are not archived yet (`pending`,
`failed`) are `TrackRow`s: they render as external songs with their `yt:` id.

Only constant SQL fragments and placeholders are ever joined into the SQL text.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from ultimatetunes.db.repository import Repository
from ultimatetunes.search.library import LibraryArtist, LibrarySong

AlbumListType = Literal[
    "random",
    "newest",
    "highest",
    "frequent",
    "recent",
    "alphabeticalByName",
    "alphabeticalByArtist",
    "starred",
    "byYear",
    "byGenre",
]

# SQLite builds may cap host parameters at 999: lookups by id go in chunks.
_CHUNK = 400


@dataclass(frozen=True)
class AlbumRow:
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
    play_count: int
    last_played_at: str | None


@dataclass(frozen=True)
class TrackRow:
    """Any track row (also pending or failed ones), with what an external song needs."""

    id: str
    status: str
    title: str
    artist_name: str
    album_name: str | None
    track_number: int | None
    year: int | None
    duration_ms: int | None
    yt_video_id: str | None
    yt_album_browse_id: str | None
    yt_artist_channel_id: str | None
    yt_thumbnail_url: str | None
    album_id: str | None
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
    " LEFT JOIN albums al ON al.id = t.album_id"
    " LEFT JOIN artists aa ON aa.id = al.artist_id"
    " LEFT JOIN starred_tracks s ON s.track_id = t.id AND s.user_id = ?"
    " LEFT JOIN user_track_stats st ON st.track_id = t.id AND st.user_id = ?"
    " WHERE t.status = 'ready'"
)

_ALBUMS = (
    "SELECT al.id, al.name, al.artist_id, ar.name AS artist_name, al.year, al.genre,"
    " al.musicbrainz_release_id, al.created_at, COUNT(t.id) AS song_count,"
    " COALESCE(SUM(t.duration_ms), 0) AS duration_ms, sa.starred_at AS starred_at,"
    " COALESCE(SUM(st.play_count), 0) AS play_count, MAX(st.last_played_at) AS last_played_at"
    " FROM albums al"
    " JOIN artists ar ON ar.id = al.artist_id"
    " JOIN tracks t ON t.album_id = al.id AND t.status = 'ready'"
    " LEFT JOIN starred_albums sa ON sa.album_id = al.id AND sa.user_id = ?"
    " LEFT JOIN user_track_stats st ON st.track_id = t.id AND st.user_id = ?"
    " WHERE 1 = 1"
)
_ALBUMS_GROUP = (
    " GROUP BY al.id, al.name, al.name_norm, al.artist_id, ar.name, ar.name_norm, al.year,"
    " al.genre, al.musicbrainz_release_id, al.created_at, sa.starred_at"
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
_ARTISTS_GROUP = (
    " GROUP BY ar.id, ar.name, ar.name_norm, ar.sort_name, ar.musicbrainz_id, sx.starred_at"
)

_TRACK_ROWS = (
    "SELECT t.id, t.status, t.title, t.artist_name, t.album_name, t.track_number, t.year,"
    " t.duration_ms, t.yt_video_id, t.yt_album_browse_id, t.yt_artist_channel_id,"
    " t.yt_thumbnail_url, t.album_id, s.starred_at AS starred_at"
    " FROM tracks t"
    " LEFT JOIN starred_tracks s ON s.track_id = t.id AND s.user_id = ?"
)

# ORDER BY per album list type (`byYear` builds its own: its direction depends on the years).
_LIST_ORDER: dict[str, str] = {
    "random": " ORDER BY RANDOM()",
    "newest": " ORDER BY al.created_at DESC, al.id",
    "highest": " ORDER BY COALESCE(SUM(st.play_count), 0) DESC, al.name_norm, al.id",
    "frequent": " ORDER BY COALESCE(SUM(st.play_count), 0) DESC, al.name_norm, al.id",
    "recent": " ORDER BY MAX(st.last_played_at) DESC, al.id",
    "alphabeticalByName": " ORDER BY al.name_norm, al.id",
    "alphabeticalByArtist": " ORDER BY ar.name_norm, al.name_norm, al.id",
    "starred": " ORDER BY sa.starred_at DESC, al.id",
    "byGenre": " ORDER BY al.name_norm, al.id",
}


def _in(column: str, count: int) -> str:
    return " AND " + column + " IN (" + ", ".join("?" * count) + ")"


def _chunks(ids: Sequence[str]) -> list[list[str]]:
    distinct = list(dict.fromkeys(ids))
    return [distinct[i : i + _CHUNK] for i in range(0, len(distinct), _CHUNK)]


class LibraryRepository(Repository):
    """Reads for one user (`user_id`: the caller, for starred and play statistics)."""

    # ------------------------------------------------------------------ songs

    def songs_by_id(self, user_id: str, ids: Sequence[str]) -> dict[str, LibrarySong]:
        """Ready songs among `ids`, by id."""
        found: dict[str, LibrarySong] = {}
        for chunk in _chunks(ids):
            sql = _SONGS + _in("t.id", len(chunk))
            for song in self.all(LibrarySong, sql, [user_id, user_id, *chunk]):
                found[song.id] = song
        return found

    def album_songs(self, user_id: str, album_id: str) -> list[LibrarySong]:
        sql = (
            _SONGS + " AND t.album_id = ?"
            " ORDER BY COALESCE(t.disc_number, 1), COALESCE(t.track_number, 0),"
            " t.title_norm, t.id"
        )
        return self.all(LibrarySong, sql, [user_id, user_id, album_id])

    def random_songs(
        self,
        user_id: str,
        size: int,
        *,
        genre: str | None,
        from_year: int | None,
        to_year: int | None,
    ) -> list[LibrarySong]:
        sql = _SONGS
        params: list[object] = [user_id, user_id]
        if genre is not None:
            sql += " AND t.genre = ?"
            params.append(genre)
        if from_year is not None:
            sql += " AND t.year >= ?"
            params.append(from_year)
        if to_year is not None:
            sql += " AND t.year <= ?"
            params.append(to_year)
        return self.all(LibrarySong, sql + " ORDER BY RANDOM() LIMIT ?", [*params, size])

    def starred_songs(self, user_id: str) -> list[TrackRow]:
        """Every starred track of the user (any status), newest star first."""
        sql = _TRACK_ROWS + " WHERE s.starred_at IS NOT NULL ORDER BY s.starred_at DESC, t.id"
        return self.all(TrackRow, sql, [user_id])

    def track_rows(self, user_id: str, ids: Sequence[str]) -> dict[str, TrackRow]:
        """Track rows (any status) among `ids`, by id."""
        found: dict[str, TrackRow] = {}
        for chunk in _chunks(ids):
            sql = _TRACK_ROWS + " WHERE 1 = 1" + _in("t.id", len(chunk))
            for row in self.all(TrackRow, sql, [user_id, *chunk]):
                found[row.id] = row
        return found

    # ------------------------------------------------------------------ albums

    def _albums(
        self, user_id: str, where: str, params: Sequence[object], tail: str
    ) -> list[AlbumRow]:
        sql = _ALBUMS + where + _ALBUMS_GROUP + tail
        return self.all(AlbumRow, sql, [user_id, user_id, *params])

    def album(self, user_id: str, album_id: str) -> AlbumRow | None:
        found = self._albums(user_id, " AND al.id = ?", [album_id], "")
        return found[0] if found else None

    def albums_by_id(self, user_id: str, ids: Sequence[str]) -> dict[str, AlbumRow]:
        found: dict[str, AlbumRow] = {}
        for chunk in _chunks(ids):
            for row in self._albums(user_id, _in("al.id", len(chunk)), chunk, ""):
                found[row.id] = row
        return found

    def artist_albums(self, user_id: str, artist_id: str) -> list[AlbumRow]:
        tail = " ORDER BY COALESCE(al.year, 0) DESC, al.name_norm, al.id"
        return self._albums(user_id, " AND al.artist_id = ?", [artist_id], tail)

    def album_list(  # noqa: PLR0913 - the parameters of getAlbumList2
        self,
        user_id: str,
        kind: AlbumListType,
        *,
        size: int,
        offset: int,
        years: tuple[int, int] | None = None,
        genre: str | None = None,
    ) -> list[AlbumRow]:
        where = ""
        params: list[object] = []
        having = ""
        if kind == "starred":
            where = " AND sa.starred_at IS NOT NULL"
        elif kind == "recent":
            having = " HAVING MAX(st.last_played_at) IS NOT NULL"
        elif kind == "byGenre":
            where = " AND al.genre = ?"
            params.append(genre)
        if kind == "byYear":
            if years is None:
                raise ValueError("byYear needs (fromYear, toYear)")
            low, high = sorted(years)
            where = " AND al.year >= ? AND al.year <= ?"
            params += [low, high]
            direction = "ASC" if years[0] <= years[1] else "DESC"
            order = f" ORDER BY al.year {direction}, al.name_norm, al.id"
        else:
            order = _LIST_ORDER[kind]
        tail = having + order + " LIMIT ? OFFSET ?"
        return self._albums(user_id, where, [*params, size, offset], tail)

    def starred_albums(self, user_id: str) -> list[AlbumRow]:
        return self._albums(
            user_id, " AND sa.starred_at IS NOT NULL", [], " ORDER BY sa.starred_at DESC, al.id"
        )

    # ------------------------------------------------------------------ artists

    def artists(self, user_id: str) -> list[LibraryArtist]:
        sql = _ARTISTS + _ARTISTS_GROUP + " ORDER BY ar.name_norm, ar.id"
        return self.all(LibraryArtist, sql, [user_id])

    def artist(self, user_id: str, artist_id: str) -> LibraryArtist | None:
        sql = _ARTISTS + " AND ar.id = ?" + _ARTISTS_GROUP
        return self.one(LibraryArtist, sql, [user_id, artist_id])

    def starred_artists(self, user_id: str) -> list[LibraryArtist]:
        sql = (
            _ARTISTS
            + " AND sx.starred_at IS NOT NULL"
            + _ARTISTS_GROUP
            + " ORDER BY sx.starred_at DESC, ar.id"
        )
        return self.all(LibraryArtist, sql, [user_id])

    # ------------------------------------------------------------------ existence

    def exists(self, table: Literal["tracks", "albums", "artists"], row_id: str) -> bool:
        sql = {
            "tracks": "SELECT 1 FROM tracks WHERE id = ?",
            "albums": "SELECT 1 FROM albums WHERE id = ?",
            "artists": "SELECT 1 FROM artists WHERE id = ?",
        }[table]
        return self.conn.execute(sql, (row_id,)).fetchone() is not None
