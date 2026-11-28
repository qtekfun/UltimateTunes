// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library.db

import androidx.room3.AutoMigration
import androidx.room3.Database
import androidx.room3.RoomDatabase

/** The local catalog of one user's library on one server. */
@Database(
    entities = [
        SongEntity::class,
        AlbumEntity::class,
        ArtistEntity::class,
        PlaylistEntity::class,
        PlaylistEntryEntity::class,
        MetaEntity::class,
        PendingChangeEntity::class
    ],
    version = 2,
    autoMigrations = [AutoMigration(from = 1, to = 2)]
)
internal abstract class CatalogDatabase : RoomDatabase() {
    abstract fun browse(): BrowseDao

    abstract fun sync(): SyncDao

    abstract fun queue(): QueueDao
}
