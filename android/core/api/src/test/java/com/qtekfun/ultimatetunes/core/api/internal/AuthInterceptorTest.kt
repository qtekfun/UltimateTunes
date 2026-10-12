// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api.internal

import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.TunesApiFactory
import com.qtekfun.ultimatetunes.core.api.model.ApiKeySecret
import java.util.concurrent.TimeUnit
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import mockwebserver3.RecordedRequest
import okhttp3.Headers.Companion.headersOf
import okhttp3.HttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test

/** The key goes only to the configured server, in the form each API expects. */
class AuthInterceptorTest {
    private val key = ApiKeySecret("utk_" + "k".repeat(43))
    private lateinit var server: MockWebServer
    private lateinit var other: MockWebServer
    private lateinit var source: InMemoryServerConfigSource
    private lateinit var client: OkHttpClient

    @BeforeEach
    fun setUp() {
        server = MockWebServer().apply { start() }
        other = MockWebServer().apply { start() }
        source = InMemoryServerConfigSource(ServerConfig(server.url("/music"), key))
        client = TunesApiFactory.httpClient(source)
    }

    @AfterEach
    fun tearDown() {
        server.close()
        other.close()
    }

    private fun send(url: HttpUrl, noAuth: Boolean = false): RecordedRequest {
        val target = if (url.port == other.port) other else server
        target.enqueue(MockResponse(code = 200, body = "{}"))
        val request = Request.Builder().url(url).apply {
            if (noAuth) tag(NoAuth::class.java, NoAuth)
        }.build()
        client.newCall(request).execute().close()
        return checkNotNull(target.takeRequest(5, TimeUnit.SECONDS))
    }

    @Test
    fun `rest requests under the base path get the OpenSubsonic parameters`() {
        val request = send(server.url("/music/rest/ping"))
        assertEquals(key.value, request.url.queryParameter("apiKey"))
        assertEquals("json", request.url.queryParameter("f"))
        assertEquals("1.16.1", request.url.queryParameter("v"))
        assertEquals(TunesApiFactory.CLIENT_NAME, request.url.queryParameter("c"))
        assertNull(request.headers["X-Api-Key"])
    }

    @Test
    fun `an apiKey already in the URL is replaced, not repeated`() {
        val request = send(server.url("/music/rest/ping?apiKey=stale"))
        assertEquals(listOf(key.value), request.url.queryParameterValues("apiKey"))
    }

    @Test
    fun `ut-v1 requests get the header and no parameter`() {
        val request = send(server.url("/music/ut/v1/me"))
        assertEquals(key.value, request.headers["X-Api-Key"])
        assertNull(request.url.queryParameter("apiKey"))
    }

    @Test
    fun `requests outside the base path, to another host or marked NoAuth get nothing`() {
        listOf(
            send(server.url("/rest/ping")),
            send(server.url("/music/other")),
            send(other.url("/music/rest/ping")),
            send(server.url("/music/ut/v1/server"), noAuth = true)
        ).forEach { request ->
            assertNull(request.url.queryParameter("apiKey"), "${request.url}")
            assertNull(request.headers["X-Api-Key"], "${request.url}")
        }
    }

    @Test
    fun `without a configuration nothing is added`() {
        source.set(null)
        val request = send(server.url("/music/rest/ping"))
        assertNull(request.url.queryParameter("apiKey"))
    }

    @Test
    fun `a redirect to another host does not carry the key`() {
        server.enqueue(
            MockResponse(
                code = 302,
                headers = headersOf("Location", other.url("/music/ut/v1/me").toString())
            )
        )
        other.enqueue(MockResponse(code = 200, body = "{}"))
        client.newCall(
            Request.Builder().url(server.url("/music/ut/v1/me")).build()
        ).execute().close()
        assertEquals(key.value, server.takeRequest().headers["X-Api-Key"])
        val redirected = checkNotNull(other.takeRequest(5, TimeUnit.SECONDS))
        assertNull(redirected.headers["X-Api-Key"])
        assertFalse(redirected.url.toString().contains(key.value))
    }
}
