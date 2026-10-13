// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.listennow

import app.cash.turbine.test
import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.ui.MainDispatcherExtension
import com.qtekfun.ultimatetunes.ui.apiWith
import com.qtekfun.ultimatetunes.ui.connectedApi
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
class RecommendationsViewModelTest {
    private lateinit var server: FakeTunesServer

    @BeforeEach
    fun setUp() {
        server = FakeTunesServer().start()
    }

    @AfterEach
    fun tearDown() {
        server.close()
    }

    /** The first non-null shelves the view model shows. */
    private suspend fun RecommendationsViewModel.awaitContent(): RecommendationsContent {
        var found: RecommendationsContent? = null
        state.test {
            while (found == null) found = awaitItem()
            cancelAndIgnoreRemainingEvents()
        }
        return checkNotNull(found)
    }

    /** Waits until the section is hidden again (the state settles back to null). */
    private suspend fun RecommendationsViewModel.awaitHidden() {
        state.test {
            var item = awaitItem()
            while (item != null) item = awaitItem()
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `the three kinds of shelf come from recommendations, with cover URLs`() = runTest {
        val content = RecommendationsViewModel(connectedApi(server)).awaitContent()

        assertFalse(content.isEmpty)
        assertEquals(listOf("Copper Fields", "Brasas"), content.recommendedForYou.map { it.title })
        assertTrue(content.recommendedForYou.first().isExternal)

        val seedShelf = content.becauseYouPlayed.single()
        assertEquals("Lighthouse Keeper", seedShelf.seedTitle)
        assertEquals(listOf("Copper Fields"), seedShelf.tracks.map { it.title })

        val source = content.sources.single()
        assertEquals("Popular on ListenBrainz · The Paper Lanterns", source.title)
        assertEquals(listOf("Paper Moons (Live)"), source.tracks.map { it.title })

        val cover = checkNotNull(content.recommendedForYou[1].coverUrl)
        assertTrue(cover.startsWith(server.baseUrl.toString()), cover)
        assertTrue("getCoverArt" in cover, cover)
        assertFalse("apiKey" in cover, "cover URLs must not carry the key")
    }

    @Test
    fun `an empty history hides the section`() = runTest {
        val viewModel = RecommendationsViewModel(connectedApi(server))
        viewModel.awaitContent()

        server.dispatcher.override("ut/v1/recommendations") {
            MockResponse(
                code = 200,
                headers = headersOf("Content-Type", "application/json"),
                body = """{"recommendedForYou":[],"becauseYouPlayed":[],"shelves":[]}"""
            )
        }
        viewModel.load()

        viewModel.awaitHidden()
    }

    @Test
    fun `a failure hides the section instead of surfacing an error`() = runTest {
        val viewModel = RecommendationsViewModel(connectedApi(server))
        viewModel.awaitContent()

        server.dispatcher.override("ut/v1/recommendations") {
            MockResponse.Builder().onResponseStart(SocketEffect.CloseSocket()).build()
        }
        viewModel.load()

        viewModel.awaitHidden()
    }

    @Test
    fun `without a server there is nothing to show`() = runTest {
        // A missing server resolves synchronously to a failure, so the section stays hidden (null).
        val viewModel = RecommendationsViewModel(apiWith(InMemoryServerConfigSource()))

        assertNull(viewModel.state.value)
    }
}
