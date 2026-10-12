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
import dagger.hilt.components.SingletonComponent
import dagger.hilt.testing.TestInstallIn
import javax.inject.Singleton
import okhttp3.OkHttpClient

/** UI tests talk to [FakeTunesApi] instead of a server. */
@Module
@TestInstallIn(components = [SingletonComponent::class], replaces = [TunesApiModule::class])
object FakeTunesApiModule {
    @Provides
    @Singleton
    fun inMemoryServerConfigSource(): InMemoryServerConfigSource = InMemoryServerConfigSource()

    @Provides
    @Singleton
    fun serverConfigSource(source: InMemoryServerConfigSource): ServerConfigSource = source

    @Provides
    @Singleton
    @TunesHttpClient
    fun tunesHttpClient(): OkHttpClient = OkHttpClient()

    @Provides
    @Singleton
    fun tunesApi(source: InMemoryServerConfigSource): TunesApi = FakeTunesApi(source)
}
