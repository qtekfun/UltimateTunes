# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Library items on the OpenSubsonic wire (contracts/openapi/opensubsonic-subset.yaml).

Songs reuse `search.render` (`library_child`, `external_child`), so a song looks the same in
`search3`, browsing, playlists, stars and the play queue. A track that is not archived yet
(`pending`, `failed`) is shown as the external song it came from: its `yt:` id, no file
fields, an empty `replayGain` (contracts/ids.md, "Resolution rules").
"""

from collections.abc import Mapping

from ultimatetunes.ids.virtual import cover_id
from ultimatetunes.library.repository import AlbumRow, TrackRow
from ultimatetunes.search.catalog import AlbumRef, ArtistRef, CatalogTrack
from ultimatetunes.search.render import external_child

type Obj = dict[str, object]


def compact(data: Mapping[str, object]) -> Obj:
    return {k: v for k, v in data.items() if v is not None}


def seconds(ms: int | None) -> int | None:
    return None if ms is None else round(ms / 1000)


def album_id3(album: AlbumRow) -> Obj:
    return compact(
        {
            "id": album.id,
            "name": album.name,
            "artist": album.artist_name,
            "artistId": album.artist_id,
            "coverArt": cover_id("album", album.id),
            "songCount": album.song_count,
            "duration": seconds(album.duration_ms) or 0,
            "playCount": album.play_count,
            "created": album.created_at,
            "starred": album.starred_at,
            "year": album.year,
            "genre": album.genre,
            "played": album.last_played_at,
            "musicBrainzId": album.musicbrainz_release_id or "",
            "genres": [{"name": album.genre}] if album.genre else [],
            "artists": [{"id": album.artist_id, "name": album.artist_name}],
            "displayArtist": album.artist_name,
        }
    )


def catalog_track(row: TrackRow) -> CatalogTrack | None:
    """The external song a not-yet-archived track came from (None without a video id)."""
    if row.yt_video_id is None:
        return None
    return CatalogTrack(
        video_id=row.yt_video_id,
        title=row.title,
        artists=(ArtistRef(row.artist_name, row.yt_artist_channel_id),),
        album=AlbumRef(row.album_name, row.yt_album_browse_id) if row.album_name else None,
        duration_s=seconds(row.duration_ms),
        year=row.year,
        track_number=row.track_number,
    )


def pending_child(row: TrackRow) -> Obj | None:
    track = catalog_track(row)
    if track is None:
        return None
    child = external_child(track)
    if row.starred_at is not None:
        child["starred"] = row.starred_at
    return child


def placeholder_child(raw_id: str) -> Obj:
    """A `yt:` item whose metadata is unknown right now (catalog unreachable)."""
    return {
        "id": raw_id,
        "isDir": False,
        "title": raw_id,
        "coverArt": raw_id,
        "type": "music",
        "mediaType": "song",
        "isVideo": False,
        "musicBrainzId": "",
        "genres": [],
        "artists": [],
        "displayArtist": "",
        "albumArtists": [],
        "displayAlbumArtist": "",
        "replayGain": {},
    }
