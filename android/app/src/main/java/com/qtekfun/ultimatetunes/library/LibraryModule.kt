// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.library

import android.content.Context
import com.qtekfun.ultimatetunes.core.api.ServerConfigSource
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.library.CatalogSync
import com.qtekfun.ultimatetunes.core.library.LibraryRepository
import com.qtekfun.ultimatetunes.core.library.LocalCatalog
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import java.time.Clock
import javax.inject.Singleton

/** The local catalog of `:core:library`: one database and one syncer per process. */
@Module
@InstallIn(SingletonComponent::class)
object LibraryModule {
    @Provides
    @Singleton
    fun localCatalog(
        @ApplicationContext context: Context,
        api: TunesApi,
        configSource: ServerConfigSource,
        clock: Clock
    ): LocalCatalog = LocalCatalog.open(context, api, configSource, clock)

    @Provides
    fun libraryRepository(catalog: LocalCatalog): LibraryRepository = catalog.repository

    @Provides
    fun catalogSync(catalog: LocalCatalog): CatalogSync = catalog.sync
}
