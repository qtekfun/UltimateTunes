// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.charts

import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.ui.MainDispatcherExtension
import com.qtekfun.ultimatetunes.ui.apiWith
import com.qtekfun.ultimatetunes.ui.awaitFirst
import com.qtekfun.ultimatetunes.ui.connectedApi
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.LoadState
import java.util.Locale
import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import mockwebserver3.SocketEffect
import okhttp3.Headers.Companion.headersOf
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.extension.ExtendWith

@ExtendWith(MainDispatcherExtension::class)
class ChartsViewModelTest {
    private lateinit var server: FakeTunesServer

    @BeforeEach
    fun setUp() {
        server = FakeTunesServer().start()
    }

    @AfterEach
    fun tearDown() {
        server.close()
    }

    @Test
    fun `the chart songs come from charts with cover URLs and a country query`() = runTest {
        val viewModel = ChartsViewModel(connectedApi(server))

        val content = (
            viewModel.state.awaitFirst { it !is LoadState.Loading } as LoadState.Ready
            ).value

        assertFalse(content.isEmpty)
        assertEquals("ES", content.country)
        assertEquals(
            listOf("Lighthouse Keeper", "Copper Fields"),
            content.tracks.map { it.title }
        )
        assertTrue(content.tracks.last().isExternal)
        val cover = checkNotNull(content.tracks.first().coverUrl)
        assertTrue(cover.startsWith(server.baseUrl.toString()), cover)
        assertFalse("apiKey" in cover, "cover URLs must not carry the key")
        assertEquals("/ut/v1/charts", server.takeRequest().url.encodedPath)
    }

    @Test
    fun `an empty chart shows an empty list, not an error`() = runTest {
        server.dispatcher.override("ut/v1/charts") {
            MockResponse(
                code = 200,
                headers = headersOf("Content-Type", "application/json"),
                body = """{"country":"ZZ","items":[]}"""
            )
        }
        val viewModel = ChartsViewModel(connectedApi(server))

        val content = (
            viewModel.state.awaitFirst { it !is LoadState.Loading } as LoadState.Ready
            ).value
        assertTrue(content.isEmpty)
        assertEquals("ZZ", content.country)
    }

    @Test
    fun `a network error can be retried`() = runTest {
        server.dispatcher.override("ut/v1/charts") {
            MockResponse.Builder().onResponseStart(SocketEffect.CloseSocket()).build()
        }
        val viewModel = ChartsViewModel(connectedApi(server))
        assertEquals(
            LoadState.Failed(LoadError.NETWORK),
            viewModel.state.awaitFirst { it !is LoadState.Loading }
        )

        server.dispatcher.clearOverrides()
        viewModel.load()

        assertTrue(viewModel.state.awaitFirst { it is LoadState.Ready } is LoadState.Ready)
    }

    @Test
    fun `without a server it is a configuration error`() = runTest {
        val viewModel = ChartsViewModel(apiWith(InMemoryServerConfigSource()))

        assertEquals(
            LoadState.Failed(LoadError.NOT_CONFIGURED),
            viewModel.state.awaitFirst { it !is LoadState.Loading }
        )
    }

    @Test
    fun `the default chart country is the device region, or none for an area code`() {
        assertEquals("US", defaultChartsCountry(Locale.forLanguageTag("en-US")))
        assertEquals("ES", defaultChartsCountry(Locale.forLanguageTag("es-ES")))
        assertNull(defaultChartsCountry(Locale.forLanguageTag("es")))
        assertNull(defaultChartsCountry(Locale.forLanguageTag("es-419")))
    }
}
