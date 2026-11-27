// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.homescreen

import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.ui.MainDispatcherExtension
import com.qtekfun.ultimatetunes.ui.TestCatalog
import com.qtekfun.ultimatetunes.ui.awaitFirst
import com.qtekfun.ultimatetunes.ui.closeForTest
import com.qtekfun.ultimatetunes.ui.connectedApi
import com.qtekfun.ultimatetunes.ui.dropConnection
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.LoadState
import kotlinx.coroutines.runBlocking
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.extension.ExtendWith

@ExtendWith(MainDispatcherExtension::class)
class HomeViewModelTest {
    private lateinit var server: FakeTunesServer
    private val catalog = TestCatalog()
    private val created = mutableListOf<HomeViewModel>()

    @BeforeEach
    fun setUp() {
        server = FakeTunesServer().start()
    }

    @AfterEach
    fun tearDown() {
        created.forEach { it.closeForTest() }
        server.close()
        catalog.close()
    }

    private fun viewModel() = HomeViewModel(connectedApi(server), catalog.repository, catalog.sync)
        .also { created += it }

    private suspend fun HomeViewModel.ready(
        predicate: (HomeContent) -> Boolean = { true }
    ): HomeContent {
        val state = state.awaitFirst {
            val content = it.content as? LoadState.Ready
            content != null && predicate(content.value)
        }
        return (state.content as LoadState.Ready).value
    }

    @Test
    fun `the shelves come from the catalog and the stations from both`() = runBlocking {
        catalog.synced()

        val content = viewModel().ready { it.stations.isNotEmpty() }

        assertEquals(listOf("Harbour Lights"), content.quickAccess.map { it.title })
        assertEquals(listOf("Harbour Lights"), content.recentlyAdded.map { it.title })
        assertEquals(listOf("Lighthouse Keeper"), content.mostPlayed.map { it.title })
        // The favourite station already starts from the only top song.
        assertEquals(
            listOf(SongId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01c001")),
            content.stations.map { it.seedId }
        )
    }

    @Test
    fun `with the server out of reach the catalog still shows`() = runBlocking {
        catalog.synced()
        server.dispatcher.override("ut/v1/listen-now") { dropConnection() }
        catalog.server.dispatcher.override("ut/v1/me") { dropConnection() }
        val viewModel = viewModel()

        viewModel.refresher.refresh()

        assertEquals(
            LoadError.NETWORK,
            viewModel.refresher.state.awaitFirst { it.error != null }.error
        )
        val state = viewModel.state.awaitFirst { it.syncError != null }
        val content = (state.content as LoadState.Ready).value
        // Only the station of the top song, which needs no answer from listen-now.
        assertEquals(listOf("Lighthouse Keeper"), content.stations.map { it.title })
        viewModel.refresher.messageShown()
        assertNull(viewModel.refresher.state.value.error)
    }

    @Test
    fun `a catalog never read says why, and a pull to refresh reads it`() = runBlocking {
        catalog.server.dispatcher.override("ut/v1/me") { dropConnection() }
        catalog.sync.sync()
        val viewModel = viewModel()
        val failed = viewModel.state.awaitFirst { it.content !is LoadState.Loading }
        assertEquals(LoadState.Failed(LoadError.NETWORK), failed.content)

        catalog.server.dispatcher.clearOverrides()
        viewModel.refresher.refresh()

        assertTrue(viewModel.ready { it.recentlyAdded.isNotEmpty() }.recentlyAdded.isNotEmpty())
    }
}
