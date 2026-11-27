// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library.db

import androidx.room3.Dao
import androidx.room3.Insert
import androidx.room3.OnConflictStrategy
import androidx.room3.Query
import androidx.room3.Transaction
import kotlinx.coroutines.flow.Flow

/** A song with the ids needed to tell what of an album or an artist is on the phone. */
internal data class SongRefRow(
    val id: String,
    val albumId: String?,
    val artistId: String?,
    val albumArtistId: String?
)

/** What the screens read. Every Flow emits again after a sync. */
@Dao
@Suppress("TooManyFunctions") // One query per list the screens show.
internal interface BrowseDao {
    @Query(
        "SELECT * FROM songs WHERE inLibrary = 1 AND instr(searchText, :first) > 0 " +
            "AND instr(searchText, :second) > 0 AND instr(searchText, :third) > 0 " +
            "ORDER BY sortName, id LIMIT :limit"
    )
    suspend fun searchSongs(
        first: String,
        second: String,
        third: String,
        limit: Int
    ): List<SongEntity>

    @Query(
        "SELECT * FROM albums WHERE inLibrary = 1 AND instr(searchText, :first) > 0 " +
            "AND instr(searchText, :second) > 0 AND instr(searchText, :third) > 0 " +
            "ORDER BY sortName, id LIMIT :limit"
    )
    suspend fun searchAlbums(
        first: String,
        second: String,
        third: String,
        limit: Int
    ): List<AlbumEntity>

    @Query(
        "SELECT * FROM artists WHERE inLibrary = 1 AND instr(searchText, :first) > 0 " +
            "AND instr(searchText, :second) > 0 AND instr(searchText, :third) > 0 " +
            "ORDER BY sortName, id LIMIT :limit"
    )
    suspend fun searchArtists(
        first: String,
        second: String,
        third: String,
        limit: Int
    ): List<ArtistEntity>

    @Query("SELECT * FROM songs WHERE inLibrary = 1 ORDER BY sortName, id")
    fun songs(): Flow<List<SongEntity>>

    @Query(
        "SELECT * FROM songs WHERE inLibrary = 1 AND albumId = :albumId " +
            "ORDER BY IFNULL(discNumber, 1), IFNULL(track, 0), sortName, id"
    )
    fun albumSongs(albumId: String): Flow<List<SongEntity>>

    @Query(
        "SELECT * FROM songs WHERE inLibrary = 1 AND " +
            "(artistId = :artistId OR albumArtistId = :artistId) ORDER BY sortName, id"
    )
    fun artistSongs(artistId: String): Flow<List<SongEntity>>

    @Query(
        "SELECT * FROM songs WHERE inLibrary = 1 " +
            "ORDER BY createdAt DESC, sortName, id LIMIT :limit"
    )
    fun recentlyAddedSongs(limit: Int): Flow<List<SongEntity>>

    @Query(
        "SELECT * FROM songs WHERE inLibrary = 1 AND playedAt IS NOT NULL " +
            "ORDER BY playedAt DESC, sortName, id LIMIT :limit"
    )
    fun recentlyPlayedSongs(limit: Int): Flow<List<SongEntity>>

    @Query(
        "SELECT * FROM songs WHERE inLibrary = 1 AND playCount > 0 " +
            "ORDER BY playCount DESC, playedAt DESC, sortName, id LIMIT :limit"
    )
    fun mostPlayedSongs(limit: Int): Flow<List<SongEntity>>

    @Query(
        "SELECT * FROM songs WHERE favouritePosition IS NOT NULL " +
            "ORDER BY favouritePosition"
    )
    fun favouriteSongs(): Flow<List<SongEntity>>

    @Query("SELECT id, albumId, artistId, albumArtistId FROM songs WHERE inLibrary = 1")
    fun songRefs(): Flow<List<SongRefRow>>

    @Query("SELECT * FROM albums WHERE inLibrary = 1 ORDER BY sortName, id")
    fun albums(): Flow<List<AlbumEntity>>

    @Query("SELECT * FROM albums WHERE id = :id")
    fun album(id: String): Flow<AlbumEntity?>

    @Query(
        "SELECT * FROM albums WHERE inLibrary = 1 AND artistId = :artistId " +
            "ORDER BY IFNULL(year, 0) DESC, sortName, id"
    )
    fun artistAlbums(artistId: String): Flow<List<AlbumEntity>>

    @Query(
        "SELECT * FROM albums WHERE inLibrary = 1 " +
            "ORDER BY createdAt DESC, sortName, id LIMIT :limit"
    )
    fun recentlyAddedAlbums(limit: Int): Flow<List<AlbumEntity>>

    @Query(
        "SELECT * FROM albums WHERE inLibrary = 1 AND playedAt IS NOT NULL " +
            "ORDER BY playedAt DESC, sortName, id LIMIT :limit"
    )
    fun recentlyPlayedAlbums(limit: Int): Flow<List<AlbumEntity>>

    @Query("SELECT * FROM albums WHERE favouritePosition IS NOT NULL ORDER BY favouritePosition")
    fun favouriteAlbums(): Flow<List<AlbumEntity>>

    @Query("SELECT * FROM artists WHERE inLibrary = 1 ORDER BY sortName, id")
    fun artists(): Flow<List<ArtistEntity>>

    @Query("SELECT * FROM artists WHERE id = :id")
    fun artist(id: String): Flow<ArtistEntity?>

    @Query("SELECT * FROM artists WHERE favouritePosition IS NOT NULL ORDER BY favouritePosition")
    fun favouriteArtists(): Flow<List<ArtistEntity>>

    @Query("SELECT * FROM playlists ORDER BY position")
    fun playlists(): Flow<List<PlaylistEntity>>

    @Query("SELECT * FROM playlists WHERE id = :id")
    fun playlist(id: String): Flow<PlaylistEntity?>

    @Query(
        "SELECT songs.* FROM playlist_entries JOIN songs ON songs.id = playlist_entries.songId " +
            "WHERE playlist_entries.playlistId = :playlistId ORDER BY playlist_entries.position"
    )
    fun playlistSongs(playlistId: String): Flow<List<SongEntity>>

    @Query("SELECT * FROM playlist_entries ORDER BY playlistId, position")
    fun allEntries(): Flow<List<PlaylistEntryEntity>>

    @Query("SELECT * FROM catalog_meta WHERE id = 0")
    fun meta(): Flow<MetaEntity?>
}

/** Everything one sync stores. */
internal data class CatalogSnapshot(
    val songs: List<SongEntity>,
    val albums: List<AlbumEntity>,
    val artists: List<ArtistEntity>,
    val playlists: List<PlaylistEntity>,
    val entries: List<PlaylistEntryEntity>
)

/** What the sync reads and writes. Each `@Transaction` happens whole or not at all. */
@Dao
@Suppress("TooManyFunctions") // One statement per table.
internal abstract class SyncDao {
    @Query("SELECT * FROM catalog_meta WHERE id = 0")
    abstract suspend fun meta(): MetaEntity?

    @Query("SELECT * FROM playlists")
    abstract suspend fun storedPlaylists(): List<PlaylistEntity>

    @Query("SELECT * FROM playlist_entries ORDER BY playlistId, position")
    abstract suspend fun storedEntries(): List<PlaylistEntryEntity>

    /** Replaces the catalog of `meta`'s owner. Pending changes are left alone. */
    @Transaction
    open suspend fun replace(snapshot: CatalogSnapshot, meta: MetaEntity) {
        deleteCatalog()
        insertSongs(snapshot.songs)
        insertAlbums(snapshot.albums)
        insertArtists(snapshot.artists)
        insertPlaylists(snapshot.playlists)
        insertEntries(snapshot.entries)
        putMeta(meta)
    }

    /** Forgets everything: the catalog, its owner and the pending changes. */
    @Transaction
    open suspend fun clearAll() {
        deleteCatalog()
        deleteMeta()
        deletePendingChanges()
    }

    /** Forgets everything and records that what comes next belongs to `ownerId`. */
    @Transaction
    open suspend fun startOver(ownerId: String, verifiedFor: String) {
        clearAll()
        putMeta(MetaEntity(ownerId = ownerId, lastSyncAt = null, verifiedFor = verifiedFor))
    }

    private suspend fun deleteCatalog() {
        deleteEntries()
        deletePlaylists()
        deleteSongs()
        deleteAlbums()
        deleteArtists()
    }

    @Query("DELETE FROM playlist_entries")
    protected abstract suspend fun deleteEntries()

    @Query("DELETE FROM playlists")
    protected abstract suspend fun deletePlaylists()

    @Query("DELETE FROM songs")
    protected abstract suspend fun deleteSongs()

    @Query("DELETE FROM albums")
    protected abstract suspend fun deleteAlbums()

    @Query("DELETE FROM artists")
    protected abstract suspend fun deleteArtists()

    @Query("DELETE FROM catalog_meta")
    protected abstract suspend fun deleteMeta()

    @Query("DELETE FROM pending_changes")
    protected abstract suspend fun deletePendingChanges()

    // The default conflict strategy aborts: a listing that repeats an id fails the whole replace.
    @Insert
    protected abstract suspend fun insertSongs(rows: List<SongEntity>)

    @Insert
    protected abstract suspend fun insertAlbums(rows: List<AlbumEntity>)

    @Insert
    protected abstract suspend fun insertArtists(rows: List<ArtistEntity>)

    @Insert
    protected abstract suspend fun insertPlaylists(rows: List<PlaylistEntity>)

    @Insert
    protected abstract suspend fun insertEntries(rows: List<PlaylistEntryEntity>)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    abstract suspend fun putMeta(meta: MetaEntity)
}

/** The queue of changes made with no connection (PLAN T35 replays it). */
@Dao
internal interface PendingChangeDao {
    @Insert
    suspend fun add(change: PendingChangeEntity): Long

    @Query("SELECT * FROM pending_changes ORDER BY seq")
    suspend fun all(): List<PendingChangeEntity>

    @Query("DELETE FROM pending_changes WHERE seq = :seq")
    suspend fun remove(seq: Long)
}
