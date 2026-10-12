// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api.fake

import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesApiFactory
import com.qtekfun.ultimatetunes.core.api.model.ApiKeySecret
import java.io.Closeable
import java.time.Clock
import java.util.concurrent.TimeUnit
import mockwebserver3.MockWebServer
import mockwebserver3.RecordedRequest
import okhttp3.HttpUrl

/**
 * A local UltimateTunes server for tests, answering with the contract examples (PLAN T02). Use it
 * from `:core:api` and, through `testFixtures(project(":core:api"))`, from `:app` tests:
 *
 * ```
 * FakeTunesServer().use { server ->
 *     val api = server.start().createApi()
 *     val album = api.album(AlbumId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01b001"))
 * }
 * ```
 *
 * Every id is accepted and answered with the same example; steer errors and states through
 * [dispatcher].
 */
class FakeTunesServer : Closeable {
    val dispatcher = ContractDispatcher()

    private val server = MockWebServer().also { it.dispatcher = dispatcher }

    /** Starts listening on a free local port; returns this server. */
    fun start(): FakeTunesServer = apply { server.start() }

    /** The server's base URL (`http://localhost:<port>/`). */
    val baseUrl: HttpUrl get() = server.url("/")

    /** A configuration for this server with [apiKey] (the valid one by default). */
    fun serverConfig(apiKey: String = API_KEY): ServerConfig =
        ServerConfig(baseUrl, ApiKeySecret(apiKey))

    /** A real [TunesApi] connected to this server, with the valid key unless [apiKey] is given. */
    fun createApi(clock: Clock = Clock.systemUTC(), apiKey: String = API_KEY): TunesApi {
        val source = InMemoryServerConfigSource(serverConfig(apiKey))
        return TunesApiFactory.create(TunesApiFactory.httpClient(source), source, clock)
    }

    /** Requests received so far. */
    val requestCount: Int get() = server.requestCount

    /** The next request received, waiting up to 5 seconds. */
    fun takeRequest(): RecordedRequest =
        checkNotNull(server.takeRequest(TIMEOUT_SECONDS, TimeUnit.SECONDS)) {
            "No request reached the fake server"
        }

    override fun close() {
        server.close()
    }

    companion object {
        /** The only key the fake accepts: the obviously fake example key of contracts/ids.md. */
        const val API_KEY = "utk_EXAMPLEexampleEXAMPLEexampleEXAMPLEexampleE"

        /** The user and password that `POST /ut/v1/keys` accepts (the contract's example). */
        const val USERNAME = "alice"
        const val PASSWORD = "correct horse battery staple"

        private const val TIMEOUT_SECONDS = 5L
    }
}
