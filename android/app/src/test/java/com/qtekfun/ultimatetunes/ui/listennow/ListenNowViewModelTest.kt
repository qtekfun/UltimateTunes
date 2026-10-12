// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.listennow

import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.ui.MainDispatcherExtension
import com.qtekfun.ultimatetunes.ui.apiWith
import com.qtekfun.ultimatetunes.ui.awaitFirst
import com.qtekfun.ultimatetunes.ui.connectedApi
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.LoadState
import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import okhttp3.Headers.Companion.headersOf
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.extension.ExtendWith

@ExtendWith(MainDispatcherExtension::class)
class ListenNowViewModelTest {
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
    fun `the shelves come from listen-now with cover URLs on the server`() = runTest {
        val viewModel = ListenNowViewModel(connectedApi(server))

        val state = viewModel.state.awaitFirst { it !is LoadState.Loading }

        val content = (state as LoadState.Ready).value
        assertFalse(content.isEmpty)
        assertEquals(
            listOf("Salt & Ember", "Harbour Lights"),
            content.recentlyPlayed.map { it.title }
        )
        assertEquals(3, content.recentlyAdded.size)
        assertEquals(AlbumId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01b003"), content.recentlyAdded[0].id)
        assertEquals(
            listOf("Lighthouse Keeper", "Tidewater", "Brasas"),
            content.mostPlayed.map { it.title }
        )
        assertEquals(214, content.mostPlayed[0].durationSec)
        assertEquals(
            SongId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01c001"),
            content.stations.single().seedId
        )
        assertEquals("The Paper Lanterns", content.stations.single().subtitle)

        val cover = checkNotNull(content.recentlyPlayed[0].coverUrl)
        assertTrue(cover.startsWith(server.baseUrl.toString()), cover)
        assertTrue("getCoverArt" in cover && "al-0199d6a2" in cover, cover)
        assertFalse("apiKey" in cover, "cover URLs must not carry the key")
    }

    @Test
    fun `without a server the screen says so and has no covers to load`() = runTest {
        val viewModel = ListenNowViewModel(apiWith(InMemoryServerConfigSource()))

        assertEquals(
            LoadState.Failed(LoadError.NOT_CONFIGURED),
            viewModel.state.awaitFirst { it !is LoadState.Loading }
        )
    }

    @Test
    fun `a refused key is an authorisation error`() = runTest {
        val viewModel = ListenNowViewModel(server.createApi(apiKey = "utk_" + "B".repeat(43)))

        assertEquals(
            LoadState.Failed(LoadError.UNAUTHORIZED),
            viewModel.state.awaitFirst { it !is LoadState.Loading }
        )
    }

    @Test
    fun `retry after a network error loads the shelves`() = runTest {
        server.dispatcher.override("ut/v1/listen-now") {
            MockResponse.Builder().onResponseStart(
                mockwebserver3.SocketEffect.CloseSocket()
            ).build()
        }
        val viewModel = ListenNowViewModel(connectedApi(server))
        assertEquals(
            LoadState.Failed(LoadError.NETWORK),
            viewModel.state.awaitFirst { it !is LoadState.Loading }
        )

        server.dispatcher.clearOverrides()
        viewModel.load()

        assertTrue(viewModel.state.awaitFirst { it !is LoadState.Loading } is LoadState.Ready)
    }

    @Test
    fun `refreshing keeps the shelves on screen and ignores repeated taps`() = runTest {
        val viewModel = ListenNowViewModel(connectedApi(server))
        val first = viewModel.state.awaitFirst { it is LoadState.Ready }
        server.dispatcher.override("ut/v1/listen-now") {
            MockResponse.Builder()
                .code(200)
                .headers(headersOf("Content-Type", "application/json"))
                .body("{}")
                .headersDelay(200, java.util.concurrent.TimeUnit.MILLISECONDS)
                .build()
        }
        val before = server.requestCount

        viewModel.load()
        viewModel.load()
        assertEquals(first, viewModel.state.value)

        val refreshed = viewModel.state.awaitFirst { it != first }
        assertTrue((refreshed as LoadState.Ready).value.isEmpty)
        assertEquals(before + 1, server.requestCount)
    }

    @Test
    fun `an unexpected answer is a server error`() = runTest {
        server.dispatcher.override("ut/v1/listen-now") {
            MockResponse(
                code = 200,
                headers = headersOf("Content-Type", "application/json"),
                body = "["
            )
        }
        val viewModel = ListenNowViewModel(connectedApi(server))

        assertEquals(
            LoadState.Failed(LoadError.SERVER),
            viewModel.state.awaitFirst { it !is LoadState.Loading }
        )
    }
}
