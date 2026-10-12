// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.artist

import androidx.lifecycle.SavedStateHandle
import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.ui.MainDispatcherExtension
import com.qtekfun.ultimatetunes.ui.awaitLoaded
import com.qtekfun.ultimatetunes.ui.awaitReady
import com.qtekfun.ultimatetunes.ui.connectedApi
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.subsonicFailure
import com.qtekfun.ultimatetunes.ui.subsonicOk
import kotlinx.coroutines.test.runTest
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.extension.ExtendWith

@ExtendWith(MainDispatcherExtension::class)
class ArtistViewModelTest {
    private lateinit var server: FakeTunesServer
    private val artistId = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01a001"

    @BeforeEach
    fun setUp() {
        server = FakeTunesServer().start()
    }

    @AfterEach
    fun tearDown() {
        server.close()
    }

    private fun viewModel() = ArtistViewModel(
        SavedStateHandle(mapOf(ArtistViewModel.ARG_ID to artistId)),
        connectedApi(server)
    )

    @Test
    fun `the artist comes with their albums`() = runTest {
        val artist = viewModel().state.awaitReady()

        assertEquals(artistId, server.takeRequest().url.queryParameter("id"))
        assertEquals("The Paper Lanterns", artist.artist.name)
        assertEquals(listOf("Harbour Lights"), artist.albums.map { it.title })
    }

    @Test
    fun `albums are listed newest first, undated last`() = runTest {
        server.dispatcher.override("rest/getArtist") {
            subsonicOk(
                "artist",
                """{"id":"a","name":"Invented","album":[
                    {"id":"1","name":"Old","year":2001},
                    {"id":"2","name":"Undated"},
                    {"id":"3","name":"New","year":2024}]}"""
            )
        }

        val artist = viewModel().state.awaitReady()

        assertEquals(listOf("New", "Old", "Undated"), artist.albums.map { it.title })
    }

    @Test
    fun `an unknown artist is an error that can be retried`() = runTest {
        server.dispatcher.override("rest/getArtist") { subsonicFailure(70) }
        val viewModel = viewModel()
        assertEquals(LoadState.Failed(LoadError.SERVER), viewModel.state.awaitLoaded())

        server.dispatcher.clearOverrides()
        viewModel.load()
        assertEquals("The Paper Lanterns", viewModel.state.awaitReady().artist.name)
    }
}
