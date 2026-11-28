// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui

import androidx.sqlite.driver.bundled.BundledSQLiteDriver
import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.core.library.CatalogSync
import com.qtekfun.ultimatetunes.core.library.CatalogSyncResult
import com.qtekfun.ultimatetunes.core.library.LibraryRepository
import com.qtekfun.ultimatetunes.core.library.LocalCatalog
import com.qtekfun.ultimatetunes.core.library.OfflineChanges
import kotlinx.coroutines.runBlocking
import org.junit.jupiter.api.Assertions.assertEquals

/**
 * The real local catalog on an in-memory database, synced from a fake server of its own: a view
 * model's requests to its server are counted apart. Empty until [synced].
 */
class TestCatalog : AutoCloseable {
    val server = FakeTunesServer().start()
    val config = InMemoryServerConfigSource(server.serverConfig())
    private val catalog =
        LocalCatalog.inMemory(apiWith(config), config, testClock, BundledSQLiteDriver())
    val repository: LibraryRepository = catalog.repository
    val sync: CatalogSync = catalog.sync
    val changes: OfflineChanges = catalog.changes

    /** This catalog after reading the server (the contract examples unless overridden). */
    fun synced(): TestCatalog = apply {
        runBlocking { assertEquals(CatalogSyncResult.Synced, sync.sync()) }
    }

    override fun close() = server.close()
}
