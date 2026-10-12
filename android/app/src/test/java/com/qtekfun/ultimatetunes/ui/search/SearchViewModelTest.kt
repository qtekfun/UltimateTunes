// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.search

import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.ArtistId
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.ui.MainDispatcherExtension
import com.qtekfun.ultimatetunes.ui.awaitFirst
import com.qtekfun.ultimatetunes.ui.connectedApi
import com.qtekfun.ultimatetunes.ui.dropConnection
import com.qtekfun.ultimatetunes.ui.jsonResponse
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.LoadState
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runTest
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.extension.ExtendWith

@OptIn(ExperimentalCoroutinesApi::class)
@ExtendWith(MainDispatcherExtension::class)
class SearchViewModelTest {
    private lateinit var server: FakeTunesServer
    private lateinit var viewModel: SearchViewModel

    @BeforeEach
    fun setUp() {
        server = FakeTunesServer().start()
        viewModel = SearchViewModel(connectedApi(server))
    }

    @AfterEach
    fun tearDown() {
        server.close()
    }

    private suspend fun results(): SearchContent =
        (viewModel.state.awaitFirst { it.results is LoadState.Ready }.results as LoadState.Ready)
            .value

    @Test
    fun `nothing is searched before typing`() {
        assertEquals(SearchUiState(), viewModel.state.value)
        viewModel.search()
        assertEquals(0, server.requestCount)
    }

    @Test
    fun `typing searches after a pause and lists library items before external ones`() = runTest {
        viewModel.onQueryChange("  lanterns ")
        assertEquals("  lanterns ", viewModel.state.value.query)

        val content = results()

        val request = server.takeRequest()
        assertEquals("/ut/v1/search", request.url.encodedPath)
        assertEquals("lanterns", request.url.queryParameter("q"))
        assertEquals(
            listOf(
                ArtistId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01a001"),
                ArtistId("ytartist:UCh5Kp2Wq7Zt3Lm9Xv1Nb4Rs")
            ),
            content.artists.map { it.id }
        )
        assertEquals(listOf(false, true), content.artists.map { it.isExternal })
        assertEquals(listOf("Harbour Lights", "Lanterns at Dusk"), content.albums.map { it.title })
        assertEquals(AlbumId("ytalbum:MPREb_k3Vd9QmT2xL"), content.albums[1].id)
        assertTrue(content.albums[1].isExternal)
        val external = content.tracks.single { it.isExternal }
        assertEquals(SongId("yt:Qx7Lm2pZ0aB"), external.id)
        assertEquals(AlbumId("ytalbum:MPREb_k3Vd9QmT2xL"), external.albumId)
        assertTrue(content.tracks.all { it.coverUrl != null })
        assertFalse(content.isEmpty)
        assertFalse(viewModel.state.value.searching)
    }

    @Test
    fun `only the last of quick keystrokes reaches the server`() = runTest {
        viewModel.onQueryChange("l")
        viewModel.onQueryChange("la")
        viewModel.onQueryChange("lan")

        results()

        assertEquals("lan", server.takeRequest().url.queryParameter("q"))
        assertEquals(1, server.requestCount)
    }

    @Test
    fun `the search key searches at once`() = runTest {
        viewModel.onQueryChange("lanterns")
        viewModel.search()
        advanceTimeBy(1)

        results()
        assertEquals(1, server.requestCount)
    }

    @Test
    fun `clearing the field forgets the results`() = runTest {
        viewModel.onQueryChange("lanterns")
        results()

        viewModel.onQueryChange("")

        assertNull(viewModel.state.value.results)
        assertEquals("", viewModel.state.value.query)
    }

    @Test
    fun `no results is an empty list, not an error`() = runTest {
        server.dispatcher.override("ut/v1/search") { jsonResponse("""{"query":"zzz"}""") }
        viewModel.onQueryChange("zzz")

        assertTrue(results().isEmpty)
    }

    @Test
    fun `a failure is shown and the search key retries`() = runTest {
        server.dispatcher.override("ut/v1/search") { dropConnection() }
        viewModel.onQueryChange("lanterns")

        val failed = viewModel.state.awaitFirst { it.results is LoadState.Failed }
        assertEquals(LoadState.Failed(LoadError.NETWORK), failed.results)

        server.dispatcher.clearOverrides()
        viewModel.search()

        assertEquals(2, results().albums.size)
    }
}
