// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.playlists

import androidx.lifecycle.SavedStateHandle
import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.library.isLocal
import com.qtekfun.ultimatetunes.core.player.offline.CollectionKind
import com.qtekfun.ultimatetunes.ui.FakeOfflineControls
import com.qtekfun.ultimatetunes.ui.MainDispatcherExtension
import com.qtekfun.ultimatetunes.ui.TestCatalog
import com.qtekfun.ultimatetunes.ui.awaitFirst
import com.qtekfun.ultimatetunes.ui.closeForTest
import com.qtekfun.ultimatetunes.ui.connectedApi
import com.qtekfun.ultimatetunes.ui.dropConnection
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.subsonicOk
import kotlinx.coroutines.flow.first
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
    private val catalog = TestCatalog()
    private val playlistId = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01e001"

    @BeforeEach
    fun setUp() {
        server = FakeTunesServer().start()
    }

    private val created = mutableListOf<PlaylistViewModel>()

    @AfterEach
    fun tearDown() {
        created.forEach { it.closeForTest() }
        server.close()
        catalog.close()
    }

    @Nested
    inner class Detail {
        private val offline = FakeOfflineControls()

        private fun viewModel() = PlaylistViewModel(
            SavedStateHandle(mapOf(PlaylistViewModel.ARG_ID to playlistId)),
            connectedApi(server),
            offline,
            catalog.changes,
            catalog.repository,
            catalog.sync
        ).also { created += it }

        private suspend fun PlaylistViewModel.ready(): PlaylistContent =
            (state.awaitFirst { it.content is LoadState.Ready }.content as LoadState.Ready).value

        private suspend fun loaded(): PlaylistViewModel = catalog.synced().let {
            viewModel()
        }.also {
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
        fun `with the server out of reach the playlist shows and can be changed`() = runTest {
            server.dispatcher.override("rest/getPlaylist") { dropConnection() }
            catalog.synced()

            val viewModel = viewModel()
            server.takeRequest()
            assertEquals("Sunday Morning", viewModel.ready().playlist.name)
            assertEquals(3, viewModel.ready().tracks.size)

            viewModel.removeAt(0)

            assertEquals(2, viewModel.ready().tracks.size)
            catalog.changes.status.first { it.count == 1 }
            val stored = catalog.repository.playlist(PlaylistId(playlistId)).first()!!
            assertEquals(listOf("Brasas", "Copper Fields"), stored.entry.map { it.title })
        }

        @Test
        fun `rename changes the name at once and queues it`() = runTest {
            val viewModel = loaded()

            viewModel.rename("  Sunday Evening ")

            assertEquals("Sunday Evening", viewModel.ready().playlist.name)
            catalog.changes.status.first { it.count == 1 }
            assertEquals(
                "Sunday Evening",
                catalog.repository.playlist(PlaylistId(playlistId)).first()?.name
            )
            assertEquals(1, server.requestCount)
        }

        @Test
        fun `renaming to the same or a blank name sends nothing`() = runTest {
            val viewModel = loaded()

            viewModel.rename("Sunday Morning")
            viewModel.rename("  ")

            assertEquals(1, server.requestCount)
        }

        @Test
        fun `removing songs updates the counts and queues each one`() = runTest {
            val viewModel = loaded()

            viewModel.removeAt(1)
            viewModel.removeAt(7)
            viewModel.removeAt(0)

            catalog.changes.status.first { it.count == 2 }
            // The row and its songs may arrive one after the other.
            val after = viewModel.state.awaitFirst {
                val playlist = (it.content as? LoadState.Ready)?.value
                playlist?.tracks?.size == 1 && playlist.playlist.songCount == 1
            }.content as LoadState.Ready
            assertEquals(listOf("Copper Fields"), after.value.tracks.map { it.title })
            val stored = catalog.repository.playlist(PlaylistId(playlistId)).first()!!
            assertEquals(listOf("Copper Fields"), stored.entry.map { it.title })
        }

        @Test
        fun `once the changes are sent the server is read again`() = runTest {
            val viewModel = loaded()
            viewModel.rename("Sent")
            catalog.changes.status.first { it.count == 1 }
            // While it waits, the server's older copy does not replace it.
            viewModel.refresh()
            server.takeRequest()
            assertEquals("Sent", viewModel.ready().playlist.name)

            catalog.changes.send()

            assertEquals("/rest/getPlaylist", server.takeRequest().url.encodedPath)
            viewModel.state.awaitFirst {
                (it.content as? LoadState.Ready)?.value?.playlist?.name == "Sunday Morning"
            }
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
            assertNull(catalog.repository.playlist(PlaylistId(playlistId)).first())
            assertEquals(1, catalog.changes.status.first().count)
        }

        @Test
        fun `a change that cannot be stored is undone and explained`() = runTest {
            val viewModel = loaded()
            catalog.config.set(catalog.server.serverConfig(apiKey = "utk_other"))

            viewModel.rename("Lost")

            val state = viewModel.state.awaitFirst { it.message != null }
            assertEquals(LoadError.STORAGE, state.message)
            assertEquals("Sunday Morning", viewModel.ready().playlist.name)
            viewModel.dismissMessage()
            viewModel.delete()
            val failed = viewModel.state.awaitFirst { it.message != null }
            assertFalse(failed.deleted)
        }

        @Test
        fun `a playlist made on the phone follows the id the server gives it`() = runTest {
            catalog.synced()
            val local = catalog.changes.createPlaylist("Road")!!
            val viewModel = PlaylistViewModel(
                SavedStateHandle(mapOf(PlaylistViewModel.ARG_ID to local.value)),
                connectedApi(server),
                offline,
                catalog.changes,
                catalog.repository,
                catalog.sync
            ).also { created += it }
            assertEquals("Road", viewModel.ready().playlist.name)
            viewModel.toggleOffline()
            viewModel.refresh()
            assertEquals(0, server.requestCount)
            assertTrue(offline.mutableSelection.value.collections.isEmpty())

            catalog.changes.send()

            assertEquals("/rest/getPlaylist", server.takeRequest().url.encodedPath)
            viewModel.state.awaitFirst {
                (it.content as? LoadState.Ready)?.value?.playlist?.id?.isLocal == false
            }
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
            // The catalog's copy may show first, until the server's answer does.
            viewModel.state.awaitFirst {
                (it.content as? LoadState.Ready)?.value?.readonly == true
            }

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
