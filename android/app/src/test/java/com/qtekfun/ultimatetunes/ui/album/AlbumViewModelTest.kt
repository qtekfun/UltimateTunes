// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.album

import androidx.lifecycle.SavedStateHandle
import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.core.api.model.ArtistId
import com.qtekfun.ultimatetunes.core.player.offline.CollectionKind
import com.qtekfun.ultimatetunes.ui.FakeOfflineControls
import com.qtekfun.ultimatetunes.ui.MainDispatcherExtension
import com.qtekfun.ultimatetunes.ui.awaitFirst
import com.qtekfun.ultimatetunes.ui.connectedApi
import com.qtekfun.ultimatetunes.ui.dropConnection
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.subsonicFailure
import com.qtekfun.ultimatetunes.ui.subsonicOk
import kotlinx.coroutines.test.runTest
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.extension.ExtendWith

@ExtendWith(MainDispatcherExtension::class)
class AlbumViewModelTest {
    private lateinit var server: FakeTunesServer
    private val libraryAlbum = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01b001"

    @BeforeEach
    fun setUp() {
        server = FakeTunesServer().start()
    }

    @AfterEach
    fun tearDown() {
        server.close()
    }

    private val offline = FakeOfflineControls()

    private fun viewModel(id: String = libraryAlbum) = AlbumViewModel(
        SavedStateHandle(mapOf(AlbumViewModel.ARG_ID to id)),
        connectedApi(server),
        offline
    )

    private suspend fun AlbumViewModel.ready(): AlbumContent =
        (state.awaitFirst { it.content is LoadState.Ready }.content as LoadState.Ready).value

    @Test
    fun `the album comes with its songs in order, artist and details`() = runTest {
        val album = viewModel().ready()

        val request = server.takeRequest()
        assertEquals("/rest/getAlbum", request.url.encodedPath)
        assertEquals(libraryAlbum, request.url.queryParameter("id"))
        assertEquals("Harbour Lights", album.album.title)
        assertEquals("The Paper Lanterns", album.album.artist)
        assertEquals(ArtistId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01a001"), album.artistId)
        assertEquals(2023, album.year)
        assertEquals("Indie Pop", album.genre)
        assertEquals(2287, album.durationSec)
        assertEquals(listOf("Lighthouse Keeper", "Tidewater"), album.tracks.map { it.title })
        assertEquals(listOf(1, 2), album.tracks.map { it.trackNumber })
        assertFalse(album.isFavourite)
        assertTrue(album.canFavourite)
    }

    @Test
    fun `a YouTube Music album has external songs and cannot be a favourite`() = runTest {
        server.dispatcher.override("rest/getAlbum") {
            subsonicOk(
                "album",
                """{"id":"ytalbum:MPREb_k3Vd9QmT2xL","name":"Lanterns at Dusk",
                    "artist":"The Paper Lanterns","song":[
                    {"id":"yt:Qx7Lm2pZ0aB","title":"Paper Moons (Live)","duration":262}]}"""
            )
        }
        val viewModel = viewModel("ytalbum:MPREb_k3Vd9QmT2xL")

        val album = viewModel.ready()
        assertTrue(album.album.isExternal)
        assertFalse(album.canFavourite)
        assertTrue(album.tracks.single().isExternal)
        // The song has no artist of its own: it takes the album's.
        assertEquals("The Paper Lanterns", album.tracks.single().artist)
        assertNull(album.album.coverUrl)

        viewModel.toggleFavourite()
        assertEquals(1, server.requestCount)
    }

    @Test
    fun `the heart stars and unstars the album`() = runTest {
        val viewModel = viewModel()
        viewModel.ready()
        server.takeRequest()

        viewModel.toggleFavourite()
        assertTrue(viewModel.ready().isFavourite)
        val star = server.takeRequest()
        assertEquals("/rest/star", star.url.encodedPath)
        assertEquals(libraryAlbum, star.url.queryParameter("albumId"))

        viewModel.toggleFavourite()
        assertFalse(viewModel.ready().isFavourite)
        assertEquals("/rest/unstar", server.takeRequest().url.encodedPath)
    }

    @Test
    fun `a refused star is undone and explained once`() = runTest {
        server.dispatcher.override("rest/star") { subsonicFailure(0) }
        val viewModel = viewModel()
        viewModel.ready()

        viewModel.toggleFavourite()

        val failed = viewModel.state.awaitFirst { it.message != null }
        assertEquals(LoadError.SERVER, failed.message)
        assertFalse((failed.content as LoadState.Ready).value.isFavourite)
        viewModel.dismissMessage()
        assertNull(viewModel.state.value.message)
    }

    @Test
    fun `nothing to toggle while loading, and errors can be retried`() = runTest {
        server.dispatcher.override("rest/getAlbum") { dropConnection() }
        val viewModel = viewModel()
        viewModel.toggleFavourite()

        val failed = viewModel.state.awaitFirst { it.content is LoadState.Failed }
        assertEquals(LoadState.Failed(LoadError.NETWORK), failed.content)
        viewModel.toggleFavourite()

        server.dispatcher.clearOverrides()
        viewModel.load()
        viewModel.load()
        assertEquals("Harbour Lights", viewModel.ready().album.title)
        // One failed getAlbum and one retry; the toggles sent nothing.
        assertEquals(2, server.requestCount)
    }

    @Test
    fun `an album can be kept offline and dropped again`() = runTest {
        val viewModel = viewModel()
        viewModel.ready()
        assertFalse(viewModel.state.value.isOffline)

        viewModel.toggleOffline()
        assertTrue(viewModel.state.awaitFirst { it.isOffline }.isOffline)
        val kept = offline.mutableSelection.value.collections.single()
        assertEquals(CollectionKind.ALBUM, kept.kind)
        assertEquals(libraryAlbum, kept.id)
        assertEquals("Harbour Lights", kept.name)

        viewModel.toggleOffline()
        assertFalse(viewModel.state.awaitFirst { !it.isOffline }.isOffline)
    }

    @Test
    fun `an album not loaded yet cannot be kept offline`() = runTest {
        server.dispatcher.override("rest/getAlbum") { dropConnection() }
        val viewModel = viewModel()
        viewModel.state.awaitFirst { it.content is LoadState.Failed }

        viewModel.toggleOffline()
        assertTrue(offline.mutableSelection.value.collections.isEmpty())
    }
}
