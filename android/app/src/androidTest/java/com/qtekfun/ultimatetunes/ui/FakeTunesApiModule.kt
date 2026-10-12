// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui

import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.ServerConfigSource
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.di.TunesApiModule
import com.qtekfun.ultimatetunes.core.api.di.TunesHttpClient
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import dagger.hilt.testing.TestInstallIn
import javax.inject.Singleton
import okhttp3.OkHttpClient

/** UI tests keep the server configuration in memory, never in the app's saved one. */
@Module
@TestInstallIn(components = [SingletonComponent::class], replaces = [TunesApiModule::class])
object FakeTunesApiModule {
    @Provides
    @Singleton
    fun inMemoryServerConfigSource(): InMemoryServerConfigSource = InMemoryServerConfigSource()

    @Provides
    @Singleton
    fun serverConfigSource(source: InMemoryServerConfigSource): ServerConfigSource = source
}

/**
 * UI tests talk to [FakeTunesApi] instead of a server. A separate `@InstallIn` module, so a test
 * that needs the real HTTP client (the store screenshots, against the demo server) can uninstall
 * it with `@UninstallModules`, which cannot remove a `@TestInstallIn` module.
 */
@Module
@InstallIn(SingletonComponent::class)
object FakeTunesApiBindings {
    @Provides
    @Singleton
    @TunesHttpClient
    fun tunesHttpClient(): OkHttpClient = OkHttpClient()

    @Provides
    @Singleton
    fun tunesApi(source: InMemoryServerConfigSource): TunesApi = FakeTunesApi(source)
}
