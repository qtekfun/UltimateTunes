// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library

import com.qtekfun.ultimatetunes.core.api.model.Album
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.Artist
import com.qtekfun.ultimatetunes.core.api.model.ArtistId
import com.qtekfun.ultimatetunes.core.api.model.ArtistRef
import com.qtekfun.ultimatetunes.core.api.model.CoverArtId
import com.qtekfun.ultimatetunes.core.api.model.Playlist
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.api.model.ReplayGain
import com.qtekfun.ultimatetunes.core.api.model.Song
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.library.db.AlbumEntity
import com.qtekfun.ultimatetunes.core.library.db.ArtistEntity
import com.qtekfun.ultimatetunes.core.library.db.GainColumns
import com.qtekfun.ultimatetunes.core.library.db.PlaylistEntity
import com.qtekfun.ultimatetunes.core.library.db.SongEntity
import java.time.Instant

// Between the rows of the catalog and the models of `:core:api`, which the screens already know.

internal fun Song.toEntity(inLibrary: Boolean): SongEntity {
    val main = artists.firstOrNull()
    val albumMain = albumArtists.firstOrNull()
    val albumArtistName = displayAlbumArtist?.ifEmpty { null } ?: albumMain?.name
    return SongEntity(
        id = id.value,
        title = title,
        artist = artist,
        displayArtist = displayArtist?.ifEmpty { null },
        artistId = (artistId ?: main?.id)?.value,
        album = album,
        albumId = albumId?.value,
        albumArtist = albumArtistName,
        albumArtistId = albumMain?.id?.value,
        coverArt = coverArt?.value,
        track = track,
        discNumber = discNumber,
        year = year,
        genre = genre,
        duration = duration,
        size = size,
        contentType = contentType,
        suffix = suffix,
        bitRate = bitRate,
        playCount = playCount ?: 0,
        createdAt = created?.toEpochMilli(),
        playedAt = played?.toEpochMilli(),
        starredAt = starred?.toEpochMilli(),
        gain = GainColumns(
            trackGain = replayGain?.trackGain,
            albumGain = replayGain?.albumGain,
            trackPeak = replayGain?.trackPeak,
            albumPeak = replayGain?.albumPeak,
            baseGain = replayGain?.baseGain
        ),
        inLibrary = inLibrary,
        favouritePosition = null,
        sortName = SearchText.of(title),
        searchText = SearchText.of(title, displayArtist ?: artist, album)
    )
}

internal fun SongEntity.toSong(): Song = Song(
    id = SongId(id),
    title = title,
    parent = albumId,
    album = album,
    artist = artist,
    track = track,
    year = year,
    genre = genre,
    coverArt = coverArt?.let(::CoverArtId),
    size = size,
    contentType = contentType,
    suffix = suffix,
    duration = duration,
    bitRate = bitRate,
    playCount = playCount,
    discNumber = discNumber,
    created = createdAt?.let(Instant::ofEpochMilli),
    starred = starredAt?.let(Instant::ofEpochMilli),
    played = playedAt?.let(Instant::ofEpochMilli),
    albumId = albumId?.let(::AlbumId),
    artistId = artistId?.let(::ArtistId),
    artists = refs(artistId, artist),
    displayArtist = displayArtist,
    albumArtists = refs(albumArtistId, albumArtist),
    displayAlbumArtist = albumArtist,
    replayGain = ReplayGain(
        trackGain = gain.trackGain,
        albumGain = gain.albumGain,
        trackPeak = gain.trackPeak,
        albumPeak = gain.albumPeak,
        baseGain = gain.baseGain
    )
)

private fun refs(id: String?, name: String?): List<ArtistRef> =
    if (id != null && name != null) listOf(ArtistRef(ArtistId(id), name)) else emptyList()

internal fun AlbumEntity.toAlbum(songs: List<SongEntity> = emptyList()): Album = Album(
    id = AlbumId(id),
    name = name,
    artist = artist,
    artistId = artistId?.let(::ArtistId),
    coverArt = coverArt?.let(::CoverArtId),
    songCount = songCount,
    duration = duration,
    playCount = playCount,
    created = createdAt?.let(Instant::ofEpochMilli),
    starred = starredAt?.let(Instant::ofEpochMilli),
    played = playedAt?.let(Instant::ofEpochMilli),
    year = year,
    genre = genre,
    artists = refs(artistId, artist),
    displayArtist = artist,
    song = songs.map { it.toSong() }
)

internal fun ArtistEntity.toArtist(albums: List<AlbumEntity> = emptyList()): Artist = Artist(
    id = ArtistId(id),
    name = name,
    coverArt = coverArt?.let(::CoverArtId),
    albumCount = albumCount,
    starred = starredAt?.let(Instant::ofEpochMilli),
    album = albums.map { it.toAlbum() }
)

internal fun PlaylistEntity.toPlaylist(songs: List<SongEntity> = emptyList()): Playlist = Playlist(
    id = PlaylistId(id),
    name = name,
    comment = comment,
    owner = owner,
    public = isPublic,
    songCount = songCount,
    duration = duration,
    created = createdAt?.let(Instant::ofEpochMilli),
    changed = changedAt?.let(Instant::ofEpochMilli),
    coverArt = coverArt?.let(::CoverArtId),
    readonly = readOnly,
    entry = songs.map { it.toSong() }
)

internal fun Playlist.toEntity(position: Int): PlaylistEntity = PlaylistEntity(
    id = id.value,
    name = name,
    comment = comment,
    owner = owner,
    isPublic = public,
    readOnly = readonly,
    songCount = songCount,
    duration = duration,
    createdAt = created?.toEpochMilli(),
    changedAt = changed?.toEpochMilli(),
    coverArt = coverArt?.value,
    position = position,
    searchText = SearchText.of(name)
)
