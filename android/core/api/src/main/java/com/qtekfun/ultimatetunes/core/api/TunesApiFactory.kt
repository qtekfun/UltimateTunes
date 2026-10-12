// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api

import com.qtekfun.ultimatetunes.core.api.internal.AuthInterceptor
import com.qtekfun.ultimatetunes.core.api.internal.OkHttpTunesApi
import java.time.Clock
import java.util.concurrent.TimeUnit
import okhttp3.OkHttpClient

/** Builds the [TunesApi] and its authenticated OkHttp client, for Hilt and for tests. */
object TunesApiFactory {
    /** The `c` parameter the server records as the play queue's `changedBy`. */
    const val CLIENT_NAME = "UltimateTunes-Android"

    private const val CONNECT_TIMEOUT_SECONDS = 15L

    /** Server answers (search with YouTube Music) take up to a few seconds; streams much longer. */
    private const val READ_TIMEOUT_SECONDS = 60L

    /**
     * An OkHttp client that adds the API key of [configSource] to requests for that server only
     * (as a network interceptor, so redirects to other hosts lose it). Pass [base] to share a
     * connection pool.
     */
    fun httpClient(
        configSource: ServerConfigSource,
        base: OkHttpClient = OkHttpClient()
    ): OkHttpClient = base.newBuilder()
        .connectTimeout(CONNECT_TIMEOUT_SECONDS, TimeUnit.SECONDS)
        .readTimeout(READ_TIMEOUT_SECONDS, TimeUnit.SECONDS)
        .addNetworkInterceptor(AuthInterceptor(configSource, CLIENT_NAME))
        .build()

    /** The [TunesApi] over [client], which must come from [httpClient] with the same [configSource]. */
    fun create(client: OkHttpClient, configSource: ServerConfigSource, clock: Clock): TunesApi =
        OkHttpTunesApi(client, configSource, clock)
}
