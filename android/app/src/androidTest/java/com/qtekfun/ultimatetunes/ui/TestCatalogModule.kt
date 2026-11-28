// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui

import com.qtekfun.ultimatetunes.core.api.ServerConfigSource
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.library.CatalogSync
import com.qtekfun.ultimatetunes.core.library.LibraryRepository
import com.qtekfun.ultimatetunes.core.library.LocalCatalog
import com.qtekfun.ultimatetunes.core.library.OfflineChanges
import com.qtekfun.ultimatetunes.library.LibraryModule
import dagger.Module
import dagger.Provides
import dagger.hilt.components.SingletonComponent
import dagger.hilt.testing.TestInstallIn
import java.time.Clock
import javax.inject.Singleton

/**
 * UI tests keep the catalog in memory: they never touch the one of the app installed on the
 * author's phone.
 */
@Module
@TestInstallIn(components = [SingletonComponent::class], replaces = [LibraryModule::class])
object TestCatalogModule {
    @Provides
    @Singleton
    fun localCatalog(api: TunesApi, configSource: ServerConfigSource, clock: Clock): LocalCatalog =
        LocalCatalog.inMemory(api, configSource, clock)

    @Provides
    fun libraryRepository(catalog: LocalCatalog): LibraryRepository = catalog.repository

    @Provides
    fun catalogSync(catalog: LocalCatalog): CatalogSync = catalog.sync

    @Provides
    fun offlineChanges(catalog: LocalCatalog): OfflineChanges = catalog.changes
}
