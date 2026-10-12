// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.radio

import androidx.lifecycle.SavedStateHandle
import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.ui.MainDispatcherExtension
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
class RadioViewModelTest {
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
    fun `favourite stations are featured and top songs become stations, without repeats`() =
        runTest {
            val viewModel = RadioViewModel(connectedApi(server))

            val content = (
                viewModel.state.awaitFirst {
                    it !is LoadState.Loading
                } as LoadState.Ready
                ).value

            assertEquals(listOf("Lighthouse Keeper Radio"), content.featured.map { it.title })
            // "Lighthouse Keeper" already seeds a favourite station, so only the other two remain.
            assertEquals(listOf("Tidewater", "Brasas"), content.fromSongs.map { it.title })
            assertEquals(
                listOf("The Paper Lanterns", "Marisol Vega"),
                content.fromSongs.map {
                    it.subtitle
                }
            )
            assertTrue(content.fromSongs.all { it.coverUrl != null })
            assertFalse(content.isEmpty)
        }

    @Test
    fun `no history means no stations`() = runTest {
        server.dispatcher.override("ut/v1/listen-now") {
            MockResponse(
                code = 200,
                headers = headersOf("Content-Type", "application/json"),
                body = "{}"
            )
        }
        val viewModel = RadioViewModel(connectedApi(server))

        val content = (
            viewModel.state.awaitFirst {
                it !is LoadState.Loading
            } as LoadState.Ready
            ).value
        assertTrue(content.isEmpty)
    }

    @Test
    fun `a failure can be retried`() = runTest {
        server.dispatcher.override("ut/v1/listen-now") {
            MockResponse.Builder().onResponseStart(
                mockwebserver3.SocketEffect.CloseSocket()
            ).build()
        }
        val viewModel = RadioViewModel(connectedApi(server))
        assertEquals(
            LoadState.Failed(LoadError.NETWORK),
            viewModel.state.awaitFirst { it !is LoadState.Loading }
        )

        server.dispatcher.clearOverrides()
        viewModel.load()

        assertTrue(viewModel.state.awaitFirst { it is LoadState.Ready } is LoadState.Ready)
    }
}

@ExtendWith(MainDispatcherExtension::class)
class StationViewModelTest {
    private lateinit var server: FakeTunesServer
    private val seed = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01c001"

    @BeforeEach
    fun setUp() {
        server = FakeTunesServer().start()
    }

    @AfterEach
    fun tearDown() {
        server.close()
    }

    private fun viewModel() = StationViewModel(
        SavedStateHandle(mapOf(StationViewModel.ARG_SEED to seed)),
        connectedApi(server)
    )

    @Test
    fun `the station asks the radio for its seed and queues the seed first`() = runTest {
        val viewModel = viewModel()

        val content = (
            viewModel.state.awaitFirst {
                it !is LoadState.Loading
            } as LoadState.Ready
            ).value

        val request = server.takeRequest()
        assertEquals("/ut/v1/radio", request.url.encodedPath)
        assertEquals(seed, request.url.queryParameter("seed"))
        assertEquals(StationViewModel.QUEUE_LENGTH.toString(), request.url.queryParameter("limit"))
        assertEquals("Lighthouse Keeper", content.seed.title)
        assertEquals(4, content.upNext.size)
        assertEquals(SongId(seed), content.queue.first().id)
        assertEquals(5, content.queue.size)
        val external = content.upNext.single { it.id == SongId("yt:Rb4Tn8wKx1c") }
        assertTrue(external.isExternal)
    }

    @Test
    fun `an error can be retried`() = runTest {
        server.dispatcher.override("ut/v1/radio") {
            MockResponse(
                code = 404,
                headers = headersOf("Content-Type", "text/html"),
                body = "<html/>"
            )
        }
        val viewModel = viewModel()
        assertEquals(
            LoadState.Failed(LoadError.SERVER),
            viewModel.state.awaitFirst { it !is LoadState.Loading }
        )

        server.dispatcher.clearOverrides()
        viewModel.load()
        viewModel.load()

        assertTrue(viewModel.state.awaitFirst { it is LoadState.Ready } is LoadState.Ready)
    }
}
