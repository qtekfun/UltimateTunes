// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library.db

import androidx.room3.Embedded
import androidx.room3.Entity
import androidx.room3.ForeignKey
import androidx.room3.Index
import androidx.room3.PrimaryKey

/*
 * The tables of the catalog. Ids are the server's opaque strings, instants are epoch milliseconds,
 * `sortName` and `searchText` are normalised with `SearchText` (lowercase, no accents).
 * `inLibrary` is false for what only a playlist or a favourite brought: a song the library does
 * not hold (yet). `favouritePosition` is the place in the favourites, newest first; null if not one.
 */

@Entity(tableName = "songs", indices = [Index("albumId"), Index("artistId"), Index("sortName")])
internal data class SongEntity(
    @PrimaryKey val id: String,
    val title: String,
    val artist: String?,
    val displayArtist: String?,
    val artistId: String?,
    val album: String?,
    val albumId: String?,
    val albumArtist: String?,
    val albumArtistId: String?,
    val coverArt: String?,
    val track: Int?,
    val discNumber: Int?,
    val year: Int?,
    val genre: String?,
    val duration: Int?,
    val size: Long?,
    val contentType: String?,
    val suffix: String?,
    val bitRate: Int?,
    val playCount: Long,
    val createdAt: Long?,
    val playedAt: Long?,
    val starredAt: Long?,
    @Embedded val gain: GainColumns,
    val inLibrary: Boolean,
    val favouritePosition: Int?,
    val sortName: String,
    val searchText: String
)

/** ReplayGain, needed to level the volume of a song played with no connection. */
internal data class GainColumns(
    val trackGain: Double?,
    val albumGain: Double?,
    val trackPeak: Double?,
    val albumPeak: Double?,
    val baseGain: Double?
)

@Entity(tableName = "albums", indices = [Index("artistId"), Index("sortName")])
internal data class AlbumEntity(
    @PrimaryKey val id: String,
    val name: String,
    val artist: String?,
    val artistId: String?,
    val coverArt: String?,
    val songCount: Int,
    val duration: Int,
    val year: Int?,
    val genre: String?,
    val playCount: Long,
    val createdAt: Long?,
    val playedAt: Long?,
    val starredAt: Long?,
    val inLibrary: Boolean,
    val favouritePosition: Int?,
    val sortName: String,
    val searchText: String
)

@Entity(tableName = "artists", indices = [Index("sortName")])
internal data class ArtistEntity(
    @PrimaryKey val id: String,
    val name: String,
    val coverArt: String?,
    val albumCount: Int,
    val starredAt: Long?,
    val inLibrary: Boolean,
    val favouritePosition: Int?,
    val sortName: String,
    val searchText: String
)

/** A playlist; `position` is its place in the server's list. */
@Entity(tableName = "playlists")
internal data class PlaylistEntity(
    @PrimaryKey val id: String,
    val name: String,
    val comment: String?,
    val owner: String?,
    val isPublic: Boolean?,
    val readOnly: Boolean?,
    val songCount: Int,
    val duration: Int,
    val createdAt: Long?,
    val changedAt: Long?,
    val coverArt: String?,
    val position: Int,
    val searchText: String
)

/** The song at `position` of a playlist; a playlist may hold the same song twice. */
@Entity(
    tableName = "playlist_entries",
    primaryKeys = ["playlistId", "position"],
    foreignKeys = [
        ForeignKey(
            entity = PlaylistEntity::class,
            parentColumns = ["id"],
            childColumns = ["playlistId"],
            onDelete = ForeignKey.CASCADE
        ),
        ForeignKey(
            entity = SongEntity::class,
            parentColumns = ["id"],
            childColumns = ["songId"],
            onDelete = ForeignKey.CASCADE
        )
    ],
    indices = [Index("songId")]
)
internal data class PlaylistEntryEntity(
    val playlistId: String,
    val position: Int,
    val songId: String
)

/** One row: whose catalog this is, and when it was last synced in full. */
@Entity(tableName = "catalog_meta")
internal data class MetaEntity(
    @PrimaryKey val id: Int = ID,
    val ownerId: String,
    val lastSyncAt: Long?,
    /**
     * Fingerprint of the connection (address and key) whose server last said it belongs to
     * [ownerId]; null until one did. The catalog is only shown to that connection.
     */
    val verifiedFor: String? = null
) {
    companion object {
        const val ID = 0
    }
}

/**
 * A change made with no connection, waiting to be sent, in the order made (`seq`). Only the
 * storage: what `kind` and `payload` hold and how they are replayed is PLAN T35's.
 */
@Entity(tableName = "pending_changes")
internal data class PendingChangeEntity(
    @PrimaryKey(autoGenerate = true) val seq: Long = 0,
    val kind: String,
    val targetId: String?,
    val payload: String,
    val createdAt: Long
)
