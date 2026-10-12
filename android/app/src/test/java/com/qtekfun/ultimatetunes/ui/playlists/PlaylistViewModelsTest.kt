// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.playlists

import androidx.lifecycle.SavedStateHandle
import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
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
import org.junit.jupiter.api.Nested
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.extension.ExtendWith

@ExtendWith(MainDispatcherExtension::class)
class PlaylistViewModelsTest {
    private lateinit var server: FakeTunesServer
    private val playlistId = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01e001"

    @BeforeEach
    fun setUp() {
        server = FakeTunesServer().start()
    }

    @AfterEach
    fun tearDown() {
        server.close()
    }

    @Nested
    inner class List {
        private fun loaded(): PlaylistsViewModel =
            PlaylistsViewModel(connectedApi(server)).also { it.load() }

        @Test
        fun `the user's playlists are listed`() = runTest {
            val viewModel = loaded()

            val state = viewModel.state.awaitFirst { it.playlists is LoadState.Ready }
            val playlist = (state.playlists as LoadState.Ready).value.single()
            assertEquals(PlaylistId(playlistId), playlist.id)
            assertEquals("Sunday Morning", playlist.name)
            assertEquals(3, playlist.songCount)
            assertEquals(663, playlist.durationSec)
        }

        @Test
        fun `a new playlist is created, added and opened once`() = runTest {
            val viewModel = loaded()
            viewModel.state.awaitFirst { it.playlists is LoadState.Ready }
            server.takeRequest()

            viewModel.create("  Morning Run ")
            viewModel.create("ignored while creating")

            val created = viewModel.state.awaitFirst { it.created != null }
            assertEquals(PlaylistId(playlistId), created.created)
            assertFalse(created.creating)
            assertEquals(2, (created.playlists as LoadState.Ready).value.size)
            val request = server.takeRequest()
            assertEquals("/rest/createPlaylist", request.url.encodedPath)
            assertEquals("Morning Run", request.url.queryParameter("name"))
            assertEquals(2, server.requestCount)

            viewModel.onCreatedOpened()
            assertNull(viewModel.state.value.created)
        }

        @Test
        fun `a blank name creates nothing`() = runTest {
            val viewModel = PlaylistsViewModel(connectedApi(server))
            viewModel.create("   ")
            assertFalse(viewModel.state.value.creating)
            assertEquals(0, server.requestCount)
        }

        @Test
        fun `a failed create is explained once`() = runTest {
            server.dispatcher.override("rest/createPlaylist") { subsonicFailure(50) }
            val viewModel = PlaylistsViewModel(connectedApi(server))

            viewModel.create("Nope")

            val failed = viewModel.state.awaitFirst { it.message != null }
            assertEquals(LoadError.SERVER, failed.message)
            assertNull(failed.created)
            viewModel.dismissMessage()
            assertNull(viewModel.state.value.message)
        }

        @Test
        fun `showing the list again reloads it in place, and errors can be retried`() = runTest {
            server.dispatcher.override("rest/getPlaylists") { dropConnection() }
            val viewModel = loaded()
            val failed = viewModel.state.awaitFirst { it.playlists is LoadState.Failed }
            assertEquals(LoadState.Failed(LoadError.NETWORK), failed.playlists)

            server.dispatcher.override("rest/getPlaylists") { subsonicOk("playlists", "{}") }
            viewModel.load()
            val empty = viewModel.state.awaitFirst { it.playlists is LoadState.Ready }
            assertEquals(LoadState.Ready(emptyList<Any>()), empty.playlists)

            server.dispatcher.clearOverrides()
            viewModel.load()
            viewModel.state.awaitFirst { (it.playlists as? LoadState.Ready)?.value?.size == 1 }
        }
    }

    @Nested
    inner class Detail {
        private fun viewModel() = PlaylistViewModel(
            SavedStateHandle(mapOf(PlaylistViewModel.ARG_ID to playlistId)),
            connectedApi(server)
        )

        private suspend fun PlaylistViewModel.ready(): PlaylistContent =
            (state.awaitFirst { it.content is LoadState.Ready }.content as LoadState.Ready).value

        private suspend fun loaded(): PlaylistViewModel = viewModel().also {
            it.ready()
            server.takeRequest()
        }

        @Test
        fun `the playlist comes with its songs, external ones marked`() = runTest {
            val playlist = viewModel().ready()

            assertEquals("Sunday Morning", playlist.playlist.name)
            assertEquals("Slow songs for slow mornings", playlist.comment)
            assertEquals(
                listOf("Lighthouse Keeper", "Brasas", "Copper Fields"),
                playlist.tracks.map {
                    it.title
                }
            )
            assertEquals(listOf(false, false, true), playlist.tracks.map { it.isExternal })
            assertFalse(playlist.readonly)
        }

        @Test
        fun `rename changes the name at once and on the server`() = runTest {
            val viewModel = loaded()

            viewModel.rename("  Sunday Evening ")

            assertEquals("Sunday Evening", viewModel.ready().playlist.name)
            val request = server.takeRequest()
            assertEquals("/rest/updatePlaylist", request.url.encodedPath)
            assertEquals(playlistId, request.url.queryParameter("playlistId"))
            assertEquals("Sunday Evening", request.url.queryParameter("name"))
        }

        @Test
        fun `renaming to the same or a blank name sends nothing`() = runTest {
            val viewModel = loaded()

            viewModel.rename("Sunday Morning")
            viewModel.rename("  ")

            assertEquals(1, server.requestCount)
        }

        @Test
        fun `removing a song sends its position and updates the counts`() = runTest {
            val viewModel = loaded()

            viewModel.removeAt(1)
            viewModel.removeAt(7)

            val after = viewModel.ready()
            assertEquals(
                listOf("Lighthouse Keeper", "Copper Fields"),
                after.tracks.map {
                    it.title
                }
            )
            assertEquals(2, after.playlist.songCount)
            assertEquals(663 - 201, after.playlist.durationSec)
            assertEquals("1", server.takeRequest().url.queryParameter("songIndexToRemove"))
            assertEquals(2, server.requestCount)
        }

        @Test
        fun `a refused change is undone and explained`() = runTest {
            server.dispatcher.override("rest/updatePlaylist") { subsonicFailure(50) }
            val viewModel = loaded()

            viewModel.rename("Mine now")

            val failed = viewModel.state.awaitFirst { it.message != null }
            assertEquals(LoadError.SERVER, failed.message)
            assertEquals("Sunday Morning", (failed.content as LoadState.Ready).value.playlist.name)
            viewModel.dismissMessage()
            assertNull(viewModel.state.value.message)
        }

        @Test
        fun `delete removes the playlist and the screen leaves`() = runTest {
            val viewModel = loaded()

            viewModel.delete()

            assertTrue(viewModel.state.awaitFirst { it.deleted }.deleted)
            val request = server.takeRequest()
            assertEquals("/rest/deletePlaylist", request.url.encodedPath)
            assertEquals(playlistId, request.url.queryParameter("id"))
        }

        @Test
        fun `a failed delete stays and explains`() = runTest {
            server.dispatcher.override("rest/deletePlaylist") { dropConnection() }
            val viewModel = loaded()

            viewModel.delete()

            val failed = viewModel.state.awaitFirst { it.message != null }
            assertEquals(LoadError.NETWORK, failed.message)
            assertFalse(failed.deleted)
        }

        @Test
        fun `someone else's playlist cannot be changed`() = runTest {
            server.dispatcher.override("rest/getPlaylist") {
                subsonicOk(
                    "playlist",
                    """{"id":"$playlistId","name":"Shared","readonly":true,"songCount":1,
                        "entry":[{"id":"s1","title":"Invented"}]}"""
                )
            }
            val viewModel = loaded()
            assertTrue(viewModel.ready().readonly)

            viewModel.rename("Mine")
            viewModel.removeAt(0)
            viewModel.delete()

            assertEquals("Shared", viewModel.ready().playlist.name)
            assertEquals(1, server.requestCount)
        }

        @Test
        fun `nothing changes before the playlist loads, and errors can be retried`() = runTest {
            server.dispatcher.override("rest/getPlaylist") { dropConnection() }
            val viewModel = viewModel()
            viewModel.rename("Too early")
            val failed = viewModel.state.awaitFirst { it.content is LoadState.Failed }
            assertEquals(LoadState.Failed(LoadError.NETWORK), failed.content)

            server.dispatcher.clearOverrides()
            viewModel.load()
            viewModel.load()
            assertEquals("Sunday Morning", viewModel.ready().playlist.name)
            assertEquals(2, server.requestCount)
        }
    }
}
