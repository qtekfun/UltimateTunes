# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Search results on the wire: OpenSubsonic `searchResult3` and `/ut/v1` `SearchResult`.

OpenSubsonic (`Child`, `AlbumID3`, `ArtistID3`): the OpenSubsonic fields we support are always
present (empty when unknown); optional fields without a value are left out. External songs
have `yt:` ids, no file fields, `coverArt` = their own id and an empty `replayGain`
(contracts/openapi/opensubsonic-subset.yaml). `/ut/v1` items add `isExternal` and
`libraryState` (contracts/openapi/ut-v1.yaml).
"""

from collections.abc import Mapping, Sequence

from ultimatetunes.ids.virtual import album_id, artist_id, song_id
from ultimatetunes.search.catalog import ArtistRef, CatalogTrack
from ultimatetunes.search.library import LibraryAlbum, LibraryArtist, LibrarySong
from ultimatetunes.search.service import Album, Artist, ExternalSong, SearchResults, Song

type Obj = dict[str, object]


def _compact(data: Mapping[str, object]) -> Obj:
    return {k: v for k, v in data.items() if v is not None}


def _seconds(ms: int | None) -> int | None:
    return None if ms is None else round(ms / 1000)


def _display(artists: Sequence[ArtistRef]) -> str:
    return ", ".join(a.name for a in artists)


def _external_artists(artists: Sequence[ArtistRef]) -> list[Obj]:
    return [
        {"id": artist_id(a.channel_id), "name": a.name} for a in artists if a.channel_id is not None
    ]


def _first_artist_id(artists: Sequence[ArtistRef]) -> str | None:
    refs = _external_artists(artists)
    return str(refs[0]["id"]) if refs else None


def _album_cover(album: str | None) -> str | None:
    return None if album is None else f"al-{album}"


# ---------------------------------------------------------------------- OpenSubsonic


def library_child(song: LibrarySong) -> Obj:
    replay_gain = _compact(
        {
            "trackGain": song.rg_track_gain_db,
            "trackPeak": song.rg_track_peak,
            "albumGain": song.rg_album_gain_db,
            "albumPeak": song.rg_album_peak,
        }
    )
    artists = [{"id": song.artist_id, "name": song.artist_name}] if song.artist_id else []
    album_artists = (
        [{"id": song.album_artist_id, "name": song.album_artist_name}]
        if song.album_artist_id and song.album_artist_name
        else artists
    )
    return _compact(
        {
            "id": song.id,
            "parent": song.album_id,
            "isDir": False,
            "title": song.title,
            "album": song.album_name,
            "artist": song.artist_name,
            "track": song.track_number,
            "year": song.year,
            "genre": song.genre,
            "coverArt": _album_cover(song.album_id),
            "size": song.size_bytes,
            "contentType": song.content_type,
            "suffix": song.format,
            "duration": _seconds(song.duration_ms),
            "bitRate": song.bit_rate_kbps,
            "samplingRate": song.sample_rate_hz,
            "channelCount": song.channels,
            "path": song.path,
            "playCount": song.play_count,
            "discNumber": song.disc_number,
            "created": song.created_at,
            "starred": song.starred_at,
            "played": song.last_played_at,
            "albumId": song.album_id,
            "artistId": song.artist_id,
            "type": "music",
            "mediaType": "song",
            "isVideo": False,
            "musicBrainzId": song.musicbrainz_recording_id or "",
            "genres": [{"name": song.genre}] if song.genre else [],
            "artists": artists,
            "displayArtist": song.artist_name,
            "albumArtists": album_artists,
            "displayAlbumArtist": song.album_artist_name or song.artist_name,
            "replayGain": replay_gain,
        }
    )


def external_child(track: CatalogTrack) -> Obj:
    artists = _external_artists(track.artists)
    browse = track.album.browse_id if track.album else None
    display = _display(track.artists)
    return _compact(
        {
            "id": song_id(track.video_id),
            "parent": album_id(browse) if browse else None,
            "isDir": False,
            "title": track.title,
            "album": track.album.name if track.album else None,
            "artist": display or None,
            "track": track.track_number,
            "year": track.year,
            "coverArt": song_id(track.video_id),
            "duration": track.duration_s,
            "albumId": album_id(browse) if browse else None,
            "artistId": _first_artist_id(track.artists),
            "type": "music",
            "mediaType": "song",
            "isVideo": False,
            "musicBrainzId": "",
            "genres": [],
            "artists": artists,
            "displayArtist": display,
            "albumArtists": artists,
            "displayAlbumArtist": display,
            "replayGain": {},
        }
    )


def child(song: Song) -> Obj:
    return external_child(song.track) if isinstance(song, ExternalSong) else library_child(song)


def album_id3(album: Album, now: str) -> Obj:
    """`now`: the `created` of an external album (required, and it has none)."""
    if isinstance(album, LibraryAlbum):
        return _compact(
            {
                "id": album.id,
                "name": album.name,
                "artist": album.artist_name,
                "artistId": album.artist_id,
                "coverArt": _album_cover(album.id),
                "songCount": album.song_count,
                "duration": _seconds(album.duration_ms),
                "created": album.created_at,
                "starred": album.starred_at,
                "year": album.year,
                "genre": album.genre,
                "musicBrainzId": album.musicbrainz_release_id or "",
                "genres": [{"name": album.genre}] if album.genre else [],
                "artists": [{"id": album.artist_id, "name": album.artist_name}],
                "displayArtist": album.artist_name,
            }
        )
    display = _display(album.artists)
    return _compact(
        {
            "id": album_id(album.browse_id),
            "name": album.title,
            "artist": display or None,
            "artistId": _first_artist_id(album.artists),
            "coverArt": album_id(album.browse_id),
            "songCount": 0,
            "duration": 0,
            "created": now,
            "year": album.year,
            "musicBrainzId": "",
            "genres": [],
            "artists": _external_artists(album.artists),
            "displayArtist": display,
        }
    )


def artist_id3(artist: Artist) -> Obj:
    if isinstance(artist, LibraryArtist):
        return _compact(
            {
                "id": artist.id,
                "name": artist.name,
                "coverArt": f"ar-{artist.id}",
                "albumCount": artist.album_count,
                "starred": artist.starred_at,
                "musicBrainzId": artist.musicbrainz_id,
                "sortName": artist.sort_name,
            }
        )
    virtual = artist_id(artist.channel_id)
    return {"id": virtual, "name": artist.name, "coverArt": virtual}


def search_result3(results: SearchResults, now: str) -> Obj:
    return {
        "artist": [artist_id3(a) for a in results.artists],
        "album": [album_id3(a, now) for a in results.albums],
        "song": [child(s) for s in results.songs],
    }


# ---------------------------------------------------------------------- /ut/v1


def track_item(song: Song) -> Obj:
    if isinstance(song, ExternalSong):
        track = song.track
        browse = track.album.browse_id if track.album else None
        return {
            "id": song_id(track.video_id),
            "title": track.title,
            "artist": _display(track.artists),
            "artistId": _first_artist_id(track.artists),
            "album": track.album.name if track.album else None,
            "albumId": album_id(browse) if browse else None,
            "durationSec": track.duration_s,
            "year": track.year,
            "coverArt": song_id(track.video_id),
            "isExternal": True,
            "libraryState": song.state,
        }
    cover = _album_cover(song.album_id) or (f"ar-{song.artist_id}" if song.artist_id else "")
    return {
        "id": song.id,
        "title": song.title,
        "artist": song.artist_name,
        "artistId": song.artist_id,
        "album": song.album_name,
        "albumId": song.album_id,
        "durationSec": _seconds(song.duration_ms),
        "year": song.year,
        "coverArt": cover,
        "isExternal": False,
        "libraryState": "ready",
    }


def album_item(album: Album) -> Obj:
    if isinstance(album, LibraryAlbum):
        return {
            "id": album.id,
            "name": album.name,
            "artist": album.artist_name,
            "artistId": album.artist_id,
            "year": album.year,
            "songCount": album.song_count,
            "coverArt": f"al-{album.id}",
            "isExternal": False,
        }
    return {
        "id": album_id(album.browse_id),
        "name": album.title,
        "artist": _display(album.artists),
        "artistId": _first_artist_id(album.artists),
        "year": album.year,
        "songCount": None,
        "coverArt": album_id(album.browse_id),
        "isExternal": True,
    }


def artist_item(artist: Artist) -> Obj:
    if isinstance(artist, LibraryArtist):
        return {
            "id": artist.id,
            "name": artist.name,
            "coverArt": f"ar-{artist.id}",
            "isExternal": False,
        }
    virtual = artist_id(artist.channel_id)
    return {"id": virtual, "name": artist.name, "coverArt": virtual, "isExternal": True}


def search_result(query: str, results: SearchResults) -> Obj:
    return {
        "query": query,
        "artists": [artist_item(a) for a in results.artists],
        "albums": [album_item(a) for a in results.albums],
        "tracks": [track_item(s) for s in results.songs],
    }
