// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library

import android.content.Context
import androidx.room3.Room
import androidx.sqlite.SQLiteDriver
import androidx.sqlite.driver.AndroidSQLiteDriver
import com.qtekfun.ultimatetunes.core.api.ServerConfigSource
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.library.db.CatalogDatabase
import java.io.File
import java.time.Clock
import kotlinx.coroutines.Dispatchers

/** The catalog: what the screens read and what keeps it up to date. One per process. */
class LocalCatalog private constructor(val repository: LibraryRepository, val sync: CatalogSync) {
    companion object {
        private const val FILE = "catalog.db"

        /** The catalog stored on this phone, never backed up. */
        fun open(
            context: Context,
            api: TunesApi,
            configSource: ServerConfigSource,
            clock: Clock
        ): LocalCatalog {
            val file = File(context.noBackupFilesDir, FILE)
            val database = Room.databaseBuilder<CatalogDatabase>(context, file.absolutePath)
                .setDriver(AndroidSQLiteDriver())
                .setQueryCoroutineContext(Dispatchers.IO)
                .build()
            return of(database, api, configSource, clock)
        }

        /** A catalog that is gone with the process, for tests. */
        fun inMemory(api: TunesApi, configSource: ServerConfigSource, clock: Clock): LocalCatalog =
            inMemory(api, configSource, clock, AndroidSQLiteDriver())

        /** [inMemory] over [driver] (JVM tests have no Android SQLite). */
        fun inMemory(
            api: TunesApi,
            configSource: ServerConfigSource,
            clock: Clock,
            driver: SQLiteDriver
        ): LocalCatalog {
            val database = Room.inMemoryDatabaseBuilder<CatalogDatabase>()
                .setDriver(driver)
                .setQueryCoroutineContext(Dispatchers.IO)
                .build()
            return of(database, api, configSource, clock)
        }

        private fun of(
            database: CatalogDatabase,
            api: TunesApi,
            configSource: ServerConfigSource,
            clock: Clock
        ): LocalCatalog {
            val syncer = CatalogSyncer(api, database, configSource, clock)
            return LocalCatalog(
                DatabaseLibraryRepository(
                    database.browse(),
                    syncer.activity,
                    configSource.config
                ),
                syncer
            )
        }
    }
}
