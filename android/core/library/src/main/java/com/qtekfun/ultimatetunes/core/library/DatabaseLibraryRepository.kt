// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library

import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.model.Album
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.Artist
import com.qtekfun.ultimatetunes.core.api.model.ArtistId
import com.qtekfun.ultimatetunes.core.api.model.Playlist
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.api.model.Song
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.library.db.AlbumEntity
import com.qtekfun.ultimatetunes.core.library.db.ArtistEntity
import com.qtekfun.ultimatetunes.core.library.db.BrowseDao
import com.qtekfun.ultimatetunes.core.library.db.SongEntity
import java.time.Instant
import kotlin.coroutines.cancellation.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.retryWhen

/**
 * [LibraryRepository] over the catalog's database. It shows the catalog only to the connection
 * whose server said it owns it: after a disconnect, or before a new connection is checked, every
 * list is empty, even if the rows are still there (a clear cut short by the process dying).
 */
@Suppress("TooManyFunctions")
internal class DatabaseLibraryRepository(
    private val dao: BrowseDao,
    activity: Flow<SyncActivity>,
    private val config: StateFlow<ServerConfig?>
) : LibraryRepository {
    private val owned: Flow<Boolean> =
        combine(config, dao.meta()) { current, meta ->
            current != null && meta?.verifiedFor == fingerprintOf(current)
        }.distinctUntilChanged()

    override val syncState: Flow<CatalogSyncState> =
        combine(activity, dao.meta(), config) { now, meta, current ->
            val mine = current != null && meta?.verifiedFor == fingerprintOf(current)
            CatalogSyncState(
                syncing = now.syncing,
                lastSuccess = meta?.lastSyncAt?.takeIf { mine }?.let(Instant::ofEpochMilli),
                error = now.error
            )
        }.distinctUntilChanged()

    @Suppress("TooGenericExceptionCaught") // Whatever the storage throws, there are no matches.
    override suspend fun search(query: String): CatalogMatches {
        val words = SearchText.of(query).split(' ').filter { it.isNotEmpty() }
        return try {
            if (words.isEmpty() || !owned.first()) CatalogMatches() else matches(words)
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            CatalogMatches()
        }
    }

    private suspend fun matches(words: List<String>): CatalogMatches {
        // The database takes the three longest, which narrow the most; an empty one matches
        // everything. Any further word is checked here, before the list is cut to its size.
        val longest = words.sortedByDescending { it.length }
        val (first, second, third) = longest + List(2) { "" }
        val rest = longest.drop(QUERIED_WORDS)

        suspend fun <T> found(
            max: Int,
            text: (T) -> String,
            query: suspend (limit: Int) -> List<T>
        ): List<T> = query(if (rest.isEmpty()) max else NO_LIMIT)
            .filter { row -> rest.all { it in text(row) } }
            .take(max)

        return CatalogMatches(
            artists = found(MAX_ARTISTS, ArtistEntity::searchText) {
                dao.searchArtists(first, second, third, it)
            }.map { it.toArtist() },
            albums = found(MAX_ALBUMS, AlbumEntity::searchText) {
                dao.searchAlbums(first, second, third, it)
            }.map { it.toAlbum() },
            songs = found(MAX_SONGS, SongEntity::searchText) {
                dao.searchSongs(first, second, third, it)
            }.map { it.toSong() }
        )
    }

    override fun songs(): Flow<List<Song>> = list { dao.songs().asSongs() }

    override fun albums(): Flow<List<Album>> = list { dao.albums().asAlbums() }

    override fun artists(): Flow<List<Artist>> = list { dao.artists().asArtists() }

    override fun playlists(): Flow<List<Playlist>> =
        list { dao.playlists().mapped { rows -> rows.map { it.toPlaylist() } } }

    override fun album(id: AlbumId): Flow<Album?> = whenOwned(null) {
        combine(dao.album(id.value), dao.albumSongs(id.value)) { album, songs ->
            album?.toAlbum(songs)
        }.distinctUntilChanged()
    }

    override fun artist(id: ArtistId): Flow<Artist?> = whenOwned(null) {
        combine(dao.artist(id.value), dao.artistAlbums(id.value)) { artist, albums ->
            artist?.toArtist(albums)
        }.distinctUntilChanged()
    }

    override fun artistSongs(id: ArtistId): Flow<List<Song>> =
        list { dao.artistSongs(id.value).asSongs() }

    override fun playlist(id: PlaylistId): Flow<Playlist?> = whenOwned(null) {
        combine(dao.playlist(id.value), dao.playlistSongs(id.value)) { playlist, songs ->
            playlist?.toPlaylist(songs)
        }.distinctUntilChanged()
    }

    override fun recentlyAddedSongs(limit: Int): Flow<List<Song>> =
        list { dao.recentlyAddedSongs(limit).asSongs() }

    override fun recentlyAddedAlbums(limit: Int): Flow<List<Album>> =
        list { dao.recentlyAddedAlbums(limit).asAlbums() }

    override fun recentlyPlayedSongs(limit: Int): Flow<List<Song>> =
        list { dao.recentlyPlayedSongs(limit).asSongs() }

    override fun recentlyPlayedAlbums(limit: Int): Flow<List<Album>> =
        list { dao.recentlyPlayedAlbums(limit).asAlbums() }

    override fun mostPlayedSongs(limit: Int): Flow<List<Song>> =
        list { dao.mostPlayedSongs(limit).asSongs() }

    override fun favouriteSongs(): Flow<List<Song>> = list { dao.favouriteSongs().asSongs() }

    override fun favouriteAlbums(): Flow<List<Album>> = list { dao.favouriteAlbums().asAlbums() }

    override fun favouriteArtists(): Flow<List<Artist>> =
        list { dao.favouriteArtists().asArtists() }

    override fun songRefs(): Flow<List<SongRef>> = list {
        dao.songRefs().mapped { rows ->
            rows.map { row ->
                SongRef(
                    id = SongId(row.id),
                    albumId = row.albumId?.let(::AlbumId),
                    artistId = row.artistId?.let(::ArtistId),
                    albumArtistId = row.albumArtistId?.let(::ArtistId)
                )
            }
        }
    }

    override fun playlistSongIds(): Flow<Map<PlaylistId, List<SongId>>> = whenOwned(emptyMap()) {
        dao.allEntries().mapped { rows ->
            rows.groupBy({ PlaylistId(it.playlistId) }, { SongId(it.songId) })
        }
    }

    /** [rows] while the catalog is the connection's own, else [hidden]. */
    @OptIn(ExperimentalCoroutinesApi::class)
    private fun <T> whenOwned(hidden: T, rows: () -> Flow<T>): Flow<T> =
        owned.flatMapLatest { if (it) rows() else flowOf(hidden) }
            // A database that cannot be read shows as empty and is tried again: it does not
            // crash whoever collects, nor leave them without updates for good.
            .retryWhen { cause, _ ->
                if (cause is Exception) {
                    emit(hidden)
                    delay(RETRY_AFTER_MS)
                }
                cause is Exception
            }

    private fun <T> list(rows: () -> Flow<List<T>>): Flow<List<T>> = whenOwned(emptyList(), rows)

    private fun Flow<List<SongEntity>>.asSongs(): Flow<List<Song>> =
        mapped { rows -> rows.map { it.toSong() } }

    private fun Flow<List<AlbumEntity>>.asAlbums(): Flow<List<Album>> =
        mapped { rows -> rows.map { it.toAlbum() } }

    private fun Flow<List<ArtistEntity>>.asArtists(): Flow<List<Artist>> =
        mapped { rows -> rows.map { it.toArtist() } }

    /** [transform] off the collector's thread (lists can be long), without repeats. */
    private fun <T, R> Flow<T>.mapped(transform: (T) -> R): Flow<R> =
        map { transform(it) }.distinctUntilChanged().flowOn(Dispatchers.Default)

    private companion object {
        // Generous, so that what is on the phone is not cut off before the screen picks it.
        const val MAX_ARTISTS = 500
        const val MAX_ALBUMS = 1_000
        const val MAX_SONGS = 3_000
        const val QUERIED_WORDS = 3

        /** SQLite reads a negative limit as none. */
        const val NO_LIMIT = -1
        const val RETRY_AFTER_MS = 30_000L
    }
}
