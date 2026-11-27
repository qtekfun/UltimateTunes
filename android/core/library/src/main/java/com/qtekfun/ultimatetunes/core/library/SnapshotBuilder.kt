// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library

import com.qtekfun.ultimatetunes.core.api.model.Album
import com.qtekfun.ultimatetunes.core.api.model.Artist
import com.qtekfun.ultimatetunes.core.api.model.Playlist
import com.qtekfun.ultimatetunes.core.api.model.Song
import com.qtekfun.ultimatetunes.core.api.model.Starred
import com.qtekfun.ultimatetunes.core.library.db.AlbumEntity
import com.qtekfun.ultimatetunes.core.library.db.ArtistEntity
import com.qtekfun.ultimatetunes.core.library.db.CatalogSnapshot
import com.qtekfun.ultimatetunes.core.library.db.PlaylistEntity
import com.qtekfun.ultimatetunes.core.library.db.PlaylistEntryEntity
import com.qtekfun.ultimatetunes.core.library.db.SongEntity

/** A playlist as listed, with its songs: read now, or kept because it did not change. */
internal sealed interface PlaylistSongs {
    val playlist: Playlist

    data class Read(override val playlist: Playlist, val songs: List<Song>) : PlaylistSongs

    /** [songIds] are all library songs of the same sync. */
    data class Kept(override val playlist: Playlist, val songIds: List<String>) : PlaylistSongs
}

/**
 * Turns what the server answered into the rows of the catalog. Albums and artists are derived from
 * the library songs; a song only a playlist or the favourites hold is stored outside the library.
 */
internal object SnapshotBuilder {
    /** [library] holds the library songs by id; it is completed with the others and reused. */
    fun build(
        library: LinkedHashMap<String, SongEntity>,
        playlists: List<PlaylistSongs>,
        starred: Starred
    ): CatalogSnapshot {
        val songs = library
        val albums = albumsOf(songs.values)
        val artists = artistsOf(songs.values, albums.values)

        val rows = mutableListOf<PlaylistEntity>()
        val entries = mutableListOf<PlaylistEntryEntity>()
        playlists.forEachIndexed { position, item ->
            rows += item.playlist.toEntity(position)
            val ids = when (item) {
                is PlaylistSongs.Kept -> item.songIds

                is PlaylistSongs.Read -> item.songs.map { song ->
                    songs.getOrPut(song.id.value) { song.toEntity(inLibrary = false) }.id
                }
            }
            val id = item.playlist.id.value
            ids.forEachIndexed { index, songId ->
                entries += PlaylistEntryEntity(id, index, songId)
            }
        }

        starSongs(songs, starred.song)
        starAlbums(albums, starred.album)
        starArtists(artists, starred.artist)
        return CatalogSnapshot(
            songs = songs.values.toList(),
            albums = albums.values.toList(),
            artists = artists.values.toList(),
            playlists = rows,
            entries = entries
        )
    }

    private fun albumsOf(songs: Collection<SongEntity>): LinkedHashMap<String, AlbumEntity> {
        val grouped = songs.filter { it.albumId != null }.groupBy { it.albumId!! }
        return grouped.entries.associateTo(LinkedHashMap()) { (id, tracks) ->
            val name = tracks.firstNotNullOfOrNull { it.album }.orEmpty()
            val artist = tracks.firstNotNullOfOrNull { it.albumArtist }
                ?: tracks.firstNotNullOfOrNull { it.displayArtist ?: it.artist }
            id to AlbumEntity(
                id = id,
                name = name,
                artist = artist,
                artistId = tracks.firstNotNullOfOrNull { it.albumArtistId }
                    ?: tracks.firstNotNullOfOrNull { it.artistId },
                coverArt = tracks.firstNotNullOfOrNull { it.coverArt },
                songCount = tracks.size,
                duration = tracks.sumOf { it.duration ?: 0 },
                year = tracks.firstNotNullOfOrNull { it.year },
                genre = tracks.firstNotNullOfOrNull { it.genre },
                playCount = tracks.sumOf { it.playCount },
                // As on the server, an album is as old as its first song.
                createdAt = tracks.mapNotNull { it.createdAt }.minOrNull(),
                playedAt = tracks.mapNotNull { it.playedAt }.maxOrNull(),
                starredAt = null,
                inLibrary = true,
                favouritePosition = null,
                sortName = SearchText.of(name),
                searchText = SearchText.of(name, artist)
            )
        }
    }

    private fun artistsOf(
        songs: Collection<SongEntity>,
        albums: Collection<AlbumEntity>
    ): LinkedHashMap<String, ArtistEntity> {
        // The album artist's name is the artist's own; a song's may add featured artists.
        val names = LinkedHashMap<String, String>()
        songs.forEach { song ->
            val id = song.albumArtistId
            if (id != null && song.albumArtist != null) names.putIfAbsent(id, song.albumArtist)
        }
        songs.forEach { song ->
            val id = song.artistId
            val name = song.artist ?: song.displayArtist
            if (id != null && name != null) names.putIfAbsent(id, name)
        }
        val byArtist = albums.groupBy { it.artistId }
        return names.entries.associateTo(LinkedHashMap()) { (id, name) ->
            val own = byArtist[id].orEmpty()
            id to ArtistEntity(
                id = id,
                name = name,
                coverArt = own.sortedByDescending { it.year ?: 0 }
                    .firstNotNullOfOrNull { it.coverArt },
                albumCount = own.size,
                starredAt = null,
                inLibrary = true,
                favouritePosition = null,
                sortName = SearchText.of(name),
                searchText = SearchText.of(name)
            )
        }
    }

    private fun starSongs(songs: MutableMap<String, SongEntity>, starred: List<Song>) {
        starred.distinctBy { it.id }.forEachIndexed { position, song ->
            val row = songs[song.id.value] ?: song.toEntity(inLibrary = false)
            songs[row.id] = row.copy(
                favouritePosition = position,
                starredAt = song.starred?.toEpochMilli()
            )
        }
        // A song a playlist brought carries the star of the playlist's answer: only this list counts.
        songs.replaceAll { _, row ->
            if (row.favouritePosition == null) row.copy(starredAt = null) else row
        }
    }

    private fun starAlbums(albums: MutableMap<String, AlbumEntity>, starred: List<Album>) {
        starred.distinctBy { it.id }.forEachIndexed { position, album ->
            val row = albums[album.id.value] ?: album.toOutsideEntity()
            albums[row.id] = row.copy(
                favouritePosition = position,
                starredAt = album.starred?.toEpochMilli()
            )
        }
    }

    private fun starArtists(artists: MutableMap<String, ArtistEntity>, starred: List<Artist>) {
        starred.distinctBy { it.id }.forEachIndexed { position, artist ->
            val row = artists[artist.id.value] ?: artist.toOutsideEntity()
            artists[row.id] = row.copy(
                favouritePosition = position,
                starredAt = artist.starred?.toEpochMilli(),
                coverArt = artist.coverArt?.value ?: row.coverArt
            )
        }
    }

    /** A favourite album none of the library songs belongs to. */
    private fun Album.toOutsideEntity() = AlbumEntity(
        id = id.value,
        name = name,
        artist = displayArtist ?: artist,
        artistId = artistId?.value,
        coverArt = coverArt?.value,
        songCount = songCount,
        duration = duration,
        year = year,
        genre = genre,
        playCount = playCount ?: 0,
        createdAt = created?.toEpochMilli(),
        playedAt = played?.toEpochMilli(),
        starredAt = null,
        inLibrary = false,
        favouritePosition = null,
        sortName = SearchText.of(name),
        searchText = SearchText.of(name, displayArtist ?: artist)
    )

    private fun Artist.toOutsideEntity() = ArtistEntity(
        id = id.value,
        name = name,
        coverArt = coverArt?.value,
        albumCount = albumCount ?: 0,
        starredAt = null,
        inLibrary = false,
        favouritePosition = null,
        sortName = SearchText.of(name),
        searchText = SearchText.of(name)
    )
}
