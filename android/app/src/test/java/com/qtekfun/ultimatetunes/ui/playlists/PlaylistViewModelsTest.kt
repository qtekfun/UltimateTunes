// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.playlists

import androidx.lifecycle.SavedStateHandle
import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.core.api.fake.form
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.player.offline.CollectionKind
import com.qtekfun.ultimatetunes.ui.FakeCatalogRefresh
import com.qtekfun.ultimatetunes.ui.FakeOfflineControls
import com.qtekfun.ultimatetunes.ui.MainDispatcherExtension
import com.qtekfun.ultimatetunes.ui.TestCatalog
import com.qtekfun.ultimatetunes.ui.awaitFirst
import com.qtekfun.ultimatetunes.ui.connectedApi
import com.qtekfun.ultimatetunes.ui.dropConnection
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.subsonicFailure
import com.qtekfun.ultimatetunes.ui.subsonicOk
import java.util.concurrent.TimeUnit
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
    private companion object {
        const val DELAY_MS = 500L
    }

    private lateinit var server: FakeTunesServer
    private val catalog = TestCatalog()
    private val refresh = FakeCatalogRefresh()
    private val playlistId = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01e001"

    @BeforeEach
    fun setUp() {
        server = FakeTunesServer().start()
    }

    @AfterEach
    fun tearDown() {
        server.close()
        catalog.close()
    }

    @Nested
    inner class Detail {
        private val offline = FakeOfflineControls()
        private val changes = PlaylistChanges()

        private fun viewModel() = PlaylistViewModel(
            SavedStateHandle(mapOf(PlaylistViewModel.ARG_ID to playlistId)),
            connectedApi(server),
            offline,
            changes,
            catalog.repository,
            catalog.sync,
            refresh
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
        fun `the catalog's copy shows with the server out of reach`() = runTest {
            catalog.synced()
            server.dispatcher.override("rest/getPlaylist") { dropConnection() }

            val viewModel = viewModel()
            server.takeRequest()

            assertEquals("Sunday Morning", viewModel.ready().playlist.name)
            assertEquals(3, viewModel.ready().tracks.size)

            // Its positions were never read from the server: removing asks for them first.
            viewModel.removeAt(0)
            assertEquals("/rest/getPlaylist", server.takeRequest().url.encodedPath)
            assertEquals(
                LoadError.NETWORK,
                viewModel.state.awaitFirst { it.message != null }.message
            )
            assertEquals(3, viewModel.ready().tracks.size)
        }

        @Test
        fun `rename changes the name at once and on the server`() = runTest {
            val viewModel = loaded()

            viewModel.rename("  Sunday Evening ")

            assertEquals("Sunday Evening", viewModel.ready().playlist.name)
            val request = server.takeRequest()
            assertEquals("/rest/updatePlaylist", request.url.encodedPath)
            assertEquals(playlistId, request.form().queryParameter("playlistId"))
            assertEquals("Sunday Evening", request.form().queryParameter("name"))
            // Read again after the change, so the answer to it has arrived.
            viewModel.refresh()
            server.takeRequest()
            assertEquals(1, refresh.requests)
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
            assertEquals("1", server.takeRequest().form().queryParameter("songIndexToRemove"))
            assertEquals(2, server.requestCount)
        }

        @Test
        fun `a refused change is explained and the playlist read again`() = runTest {
            server.dispatcher.override("rest/updatePlaylist") { subsonicFailure(50) }
            val viewModel = loaded()

            viewModel.rename("Mine now")

            val failed = viewModel.state.awaitFirst {
                it.message != null &&
                    (it.content as? LoadState.Ready)?.value?.playlist?.name == "Sunday Morning"
            }
            assertEquals(LoadError.SERVER, failed.message)
            assertEquals("/rest/updatePlaylist", server.takeRequest().url.encodedPath)
            assertEquals("/rest/getPlaylist", server.takeRequest().url.encodedPath)
            viewModel.dismissMessage()
            assertNull(viewModel.state.value.message)
        }

        @Test
        fun `after a refusal the server's current playlist shows, not the old copy`() = runTest {
            val viewModel = loaded()
            server.dispatcher.override("rest/updatePlaylist") { subsonicFailure(70) }
            server.dispatcher.override("rest/getPlaylist") {
                subsonicOk(
                    "playlist",
                    """{"id":"$playlistId","name":"Renamed Elsewhere","songCount":0,
                        "duration":0,"entry":[]}"""
                )
            }

            viewModel.removeAt(0)

            val state = viewModel.state.awaitFirst {
                (it.content as? LoadState.Ready)?.value?.playlist?.name == "Renamed Elsewhere"
            }
            assertEquals(emptyList<Any>(), (state.content as LoadState.Ready).value.tracks)
        }

        @Test
        fun `a playlist can be kept offline and dropped again`() = runTest {
            val viewModel = loaded()
            assertFalse(viewModel.state.value.isOffline)

            viewModel.toggleOffline()
            assertTrue(viewModel.state.awaitFirst { it.isOffline }.isOffline)
            val kept = offline.mutableSelection.value.collections.single()
            assertEquals(CollectionKind.PLAYLIST, kept.kind)
            assertEquals(playlistId, kept.id)
            assertEquals("Sunday Morning", kept.name)

            viewModel.toggleOffline()
            assertFalse(viewModel.state.awaitFirst { !it.isOffline }.isOffline)
            assertTrue(offline.mutableSelection.value.collections.isEmpty())
        }

        @Test
        fun `deleting a playlist kept offline stops keeping it`() = runTest {
            val viewModel = loaded()
            viewModel.toggleOffline()
            viewModel.state.awaitFirst { it.isOffline }

            viewModel.delete()

            viewModel.state.awaitFirst { it.deleted && !it.isOffline }
            assertTrue(offline.mutableSelection.value.collections.isEmpty())
        }

        @Test
        fun `a change to a kept playlist syncs at once`() = runTest {
            val viewModel = loaded()
            viewModel.toggleOffline()
            viewModel.state.awaitFirst { it.isOffline }

            viewModel.rename("Synced")
            server.takeRequest()
            viewModel.refresh()
            server.takeRequest()

            assertEquals(1, offline.syncs)
        }

        @Test
        fun `a change that cannot be sent is undone even with no connection`() = runTest {
            val viewModel = loaded()
            server.dispatcher.override("rest/updatePlaylist") { dropConnection() }
            server.dispatcher.override("rest/getPlaylist") { dropConnection() }

            viewModel.rename("Lost")

            val state = viewModel.state.awaitFirst { it.message != null }
            assertEquals(
                "Sunday Morning",
                (state.content as LoadState.Ready).value.playlist.name
            )
        }

        @Test
        fun `an answer asked before a change does not undo it`() = runTest {
            val viewModel = loaded()
            server.dispatcher.override("rest/getPlaylist") {
                subsonicOk(
                    "playlist",
                    """{"id":"$playlistId","name":"Stale","songCount":0,"duration":0,
                        "entry":[]}"""
                ).newBuilder().headersDelay(DELAY_MS, TimeUnit.MILLISECONDS).build()
            }

            viewModel.refresh()
            assertEquals("/rest/getPlaylist", server.takeRequest().url.encodedPath)
            viewModel.rename("Newer")
            assertEquals("/rest/updatePlaylist", server.takeRequest().url.encodedPath)

            assertEquals("Newer", viewModel.ready().playlist.name)
        }

        @Test
        fun `a refresh queued between two changes does not undo the second`() = runTest {
            val viewModel = loaded()
            var reads = 0
            server.dispatcher.override("rest/updatePlaylist") {
                subsonicOk("ignored", "{}").newBuilder()
                    .headersDelay(DELAY_MS, TimeUnit.MILLISECONDS)
                    .build()
            }
            server.dispatcher.override("rest/getPlaylist") {
                val name = if (reads++ == 0) "One" else "Two"
                subsonicOk(
                    "playlist",
                    """{"id":"$playlistId","name":"$name","songCount":0,"duration":0,
                        "entry":[]}"""
                )
            }

            viewModel.rename("One")
            viewModel.refresh()
            viewModel.rename("Two")

            val paths = List(4) { server.takeRequest().url.encodedPath.substringAfterLast('/') }
            assertEquals(
                listOf("updatePlaylist", "getPlaylist", "updatePlaylist", "getPlaylist"),
                paths
            )
            viewModel.state.awaitFirst {
                (it.content as? LoadState.Ready)?.value?.tracks?.isEmpty() == true
            }
            assertEquals("Two", viewModel.ready().playlist.name)
        }

        @Test
        fun `after a failure that could not be checked, removing reads the list first`() = runTest {
            val viewModel = loaded()
            server.dispatcher.override("rest/updatePlaylist") { subsonicFailure(0) }
            server.dispatcher.override("rest/getPlaylist") { subsonicFailure(0) }
            viewModel.removeAt(0)
            viewModel.state.awaitFirst { it.message != null }
            server.takeRequest()
            server.takeRequest()

            viewModel.removeAt(0)

            assertEquals("/rest/getPlaylist", server.takeRequest().url.encodedPath)
        }

        @Test
        fun `songs added elsewhere show in the open playlist`() = runTest {
            val viewModel = loaded()

            changes.changed(PlaylistId(playlistId))

            assertEquals("/rest/getPlaylist", server.takeRequest().url.encodedPath)
            viewModel.ready()
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
