// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api.di

import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.ServerConfigSource
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesApiFactory
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import java.time.Clock
import javax.inject.Qualifier
import javax.inject.Singleton
import okhttp3.OkHttpClient

/**
 * The OkHttp client that authenticates against the configured server (see `TunesApi.streamUrl`):
 * inject it into Media3's `OkHttpDataSource.Factory` and the image loader.
 */
@Qualifier
@Retention(AnnotationRetention.BINARY)
annotation class TunesHttpClient

@Module
@InstallIn(SingletonComponent::class)
object TunesApiModule {
    @Provides
    @Singleton
    fun inMemoryServerConfigSource(): InMemoryServerConfigSource = InMemoryServerConfigSource()

    @Provides
    @Singleton
    fun serverConfigSource(source: InMemoryServerConfigSource): ServerConfigSource = source

    @Provides
    @Singleton
    @TunesHttpClient
    fun tunesHttpClient(configSource: ServerConfigSource): OkHttpClient =
        TunesApiFactory.httpClient(configSource)

    @Provides
    @Singleton
    fun tunesApi(
        @TunesHttpClient client: OkHttpClient,
        configSource: ServerConfigSource,
        clock: Clock
    ): TunesApi = TunesApiFactory.create(client, configSource, clock)
}

/** The app's single [Clock]: every time-dependent piece takes it, so tests can fix the time. */
@Module
@InstallIn(SingletonComponent::class)
object ClockModule {
    @Provides
    @Singleton
    fun clock(): Clock = Clock.systemUTC()
}
