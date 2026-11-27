// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library

import com.qtekfun.ultimatetunes.core.api.model.Album
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.Artist
import com.qtekfun.ultimatetunes.core.api.model.ArtistId
import com.qtekfun.ultimatetunes.core.api.model.Playlist
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.api.model.Song
import com.qtekfun.ultimatetunes.core.api.model.SongId
import kotlinx.coroutines.flow.Flow

/**
 * A library song and where it belongs, to tell which albums and artists have something on the
 * phone (matched against the offline downloads).
 */
data class SongRef(
    val id: SongId,
    val albumId: AlbumId?,
    val artistId: ArtistId?,
    val albumArtistId: ArtistId?
)

/**
 * The library as the phone knows it, readable with no connection. Every Flow emits what is stored
 * and again whenever it changes. The models are those of `:core:api`.
 */
@Suppress("TooManyFunctions") // One Flow per thing the screens show.
interface LibraryRepository {
    val syncState: Flow<CatalogSyncState>

    /** Library songs by title. */
    fun songs(): Flow<List<Song>>

    /** Library albums by name, without their songs. */
    fun albums(): Flow<List<Album>>

    /** Library artists by name, without their albums. */
    fun artists(): Flow<List<Artist>>

    /** The playlists the user sees (others' public ones are `readonly`), without their songs. */
    fun playlists(): Flow<List<Playlist>>

    /** The album with its songs in disc and track order; null when the catalog has no such one. */
    fun album(id: AlbumId): Flow<Album?>

    /** The artist with its albums, newest year first; null when unknown. */
    fun artist(id: ArtistId): Flow<Artist?>

    /** The artist's library songs by title, those on others' albums too. */
    fun artistSongs(id: ArtistId): Flow<List<Song>>

    /**
     * The playlist with its songs in order; null when unknown. A song not in the library yet has a
     * `yt:` id.
     */
    fun playlist(id: PlaylistId): Flow<Playlist?>

    fun recentlyAddedSongs(limit: Int): Flow<List<Song>>

    fun recentlyAddedAlbums(limit: Int): Flow<List<Album>>

    fun recentlyPlayedSongs(limit: Int): Flow<List<Song>>

    fun recentlyPlayedAlbums(limit: Int): Flow<List<Album>>

    fun mostPlayedSongs(limit: Int): Flow<List<Song>>

    /** Favourite songs, newest first, those not in the library yet included. */
    fun favouriteSongs(): Flow<List<Song>>

    fun favouriteAlbums(): Flow<List<Album>>

    fun favouriteArtists(): Flow<List<Artist>>

    /** Every library song's id with its album and artists. */
    fun songRefs(): Flow<List<SongRef>>

    /** The song ids of each playlist that has any, in order. */
    fun playlistSongIds(): Flow<Map<PlaylistId, List<SongId>>>
}
