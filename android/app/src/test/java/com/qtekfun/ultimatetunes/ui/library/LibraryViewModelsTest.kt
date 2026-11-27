// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.library

import androidx.lifecycle.SavedStateHandle
import com.qtekfun.ultimatetunes.availability.Availability
import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.core.api.fake.form
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.ArtistId
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.player.offline.CollectionKind
import com.qtekfun.ultimatetunes.ui.FakeCatalogRefresh
import com.qtekfun.ultimatetunes.ui.FakeOfflineControls
import com.qtekfun.ultimatetunes.ui.FakePhoneAvailability
import com.qtekfun.ultimatetunes.ui.MainDispatcherExtension
import com.qtekfun.ultimatetunes.ui.TestCatalog
import com.qtekfun.ultimatetunes.ui.awaitFirst
import com.qtekfun.ultimatetunes.ui.awaitReady
import com.qtekfun.ultimatetunes.ui.closeForTest
import com.qtekfun.ultimatetunes.ui.connectedApi
import com.qtekfun.ultimatetunes.ui.dropConnection
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.subsonicFailure
import com.qtekfun.ultimatetunes.ui.tile
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.runBlocking
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

private const val PLAYLIST = "0199d6a2-4c1e-7b3a-9f10-2a6c8e01e001"
private val KEEPER = SongId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01c001")

@ExtendWith(MainDispatcherExtension::class)
class LibraryViewModelsTest {
    private lateinit var server: FakeTunesServer
    private val catalog = TestCatalog()
    private val refresh = FakeCatalogRefresh()
    private val phone = FakePhoneAvailability()
    private val offline = FakeOfflineControls()
    private val created = mutableListOf<androidx.lifecycle.ViewModel>()

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

    private fun library(saved: SavedStateHandle = SavedStateHandle()) = LibraryViewModel(
        saved,
        connectedApi(server),
        catalog.repository,
        catalog.sync,
        refresh,
        phone,
        NoOfflineDownloads,
        offline
    ).also { created += it }

    private suspend fun LibraryViewModel.items(
        filter: LibraryFilter,
        predicate: (LibraryItems) -> Boolean = { true }
    ): LibraryItems {
        val state = state.awaitFirst {
            val items = (it.items as? LoadState.Ready)?.value
            it.filter == filter && items != null && predicate(items)
        }
        return (state.items as LoadState.Ready).value
    }

    @Nested
    inner class Library {
        @Test
        fun `each filter lists the catalog, with no request of its own`() = runBlocking {
            catalog.synced()
            val viewModel = library()

            val playlists = viewModel.items(LibraryFilter.PLAYLISTS) as LibraryItems.Playlists
            assertEquals(listOf("Sunday Morning"), playlists.playlists.map { it.name })
            assertEquals(1, viewModel.state.value.favouriteCount)

            viewModel.select(LibraryFilter.ALBUMS)
            val albums = viewModel.items(LibraryFilter.ALBUMS) as LibraryItems.Albums
            assertEquals(listOf("Harbour Lights"), albums.albums.map { it.title })

            viewModel.select(LibraryFilter.ARTISTS)
            val artists = viewModel.items(LibraryFilter.ARTISTS) as LibraryItems.Artists
            assertEquals(listOf("The Paper Lanterns"), artists.artists.map { it.name })

            viewModel.select(LibraryFilter.SONGS)
            val songs = viewModel.items(LibraryFilter.SONGS) as LibraryItems.Songs
            assertEquals(listOf("Lighthouse Keeper"), songs.songs.map { it.title })

            assertEquals(3, viewModel.playlistTracks(PlaylistId(PLAYLIST)).size)
            val artist = artists.artists.single().id
            assertEquals(1, viewModel.artistTracks(artist).size)
            assertEquals(0, server.requestCount)
        }

        @Test
        fun `on this phone keeps what the phone holds, and offline mode forces it`() = runBlocking {
            catalog.synced()
            val viewModel = library()
            viewModel.select(LibraryFilter.SONGS)
            viewModel.items(LibraryFilter.SONGS) { !it.isEmpty }

            viewModel.setOnPhoneOnly(true)
            viewModel.items(LibraryFilter.SONGS) { it.isEmpty }

            phone.availability.value = Availability(
                songs = setOf(KEEPER),
                albums = setOf(AlbumId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01b001")),
                artists = setOf(ArtistId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01a001")),
                playlists = setOf(PlaylistId(PLAYLIST))
            )
            viewModel.items(LibraryFilter.SONGS) { !it.isEmpty }
            for (filter in listOf(
                LibraryFilter.ALBUMS,
                LibraryFilter.ARTISTS,
                LibraryFilter.PLAYLISTS
            )) {
                viewModel.select(filter)
                viewModel.items(filter) { !it.isEmpty }
            }

            viewModel.setOnPhoneOnly(false)
            phone.availability.value = Availability(offlineMode = true)
            viewModel.items(LibraryFilter.PLAYLISTS) { it.isEmpty }
            assertTrue(viewModel.state.value.onPhoneOnly)
            assertTrue(viewModel.state.value.offlineMode)
        }

        @Test
        fun `the filter chosen is restored`() = runBlocking {
            catalog.synced()
            val saved = SavedStateHandle()
            library(saved).select(LibraryFilter.ARTISTS)

            library(saved).items(LibraryFilter.ARTISTS)
            Unit
        }

        @Test
        fun `a catalog never read says why`() = runBlocking {
            catalog.server.dispatcher.override("ut/v1/me") { dropConnection() }
            catalog.sync.sync()

            val state = library().state.awaitFirst { it.items !is LoadState.Loading }

            assertEquals(LoadState.Failed(LoadError.NETWORK), state.items)
        }

        @Test
        fun `a playlist is kept offline from its row and dropped again`() = runBlocking {
            catalog.synced()
            val viewModel = library()
            val playlist = (
                viewModel.items(LibraryFilter.PLAYLISTS) as LibraryItems.Playlists
                ).playlists.single()

            viewModel.toggleOffline(playlist)
            viewModel.state.awaitFirst { playlist.id in it.keptPlaylists }
            assertEquals(
                CollectionKind.PLAYLIST,
                offline.mutableSelection.value.collections.single().kind
            )

            viewModel.toggleOffline(playlist)
            viewModel.state.awaitFirst { it.keptPlaylists.isEmpty() }
            Unit
        }

        @Test
        fun `a new playlist is created, opened once and synced`() = runBlocking {
            val viewModel = library()

            viewModel.create("  ")
            viewModel.create("  Morning Run ")

            val state = viewModel.state.awaitFirst { it.newPlaylist.created != null }
            assertEquals(PlaylistId(PLAYLIST), state.newPlaylist.created)
            val request = server.takeRequest()
            assertEquals("/rest/createPlaylist", request.url.encodedPath)
            assertEquals("Morning Run", request.form().queryParameter("name"))
            assertEquals(1, server.requestCount)
            assertEquals(1, refresh.requests)

            viewModel.onCreatedOpened()
            viewModel.state.awaitFirst { it.newPlaylist.created == null }
            Unit
        }

        @Test
        fun `a failed create is explained once`() = runBlocking {
            server.dispatcher.override("rest/createPlaylist") { subsonicFailure(50) }
            val viewModel = library()

            viewModel.create("Nope")

            val failed = viewModel.state.awaitFirst { it.newPlaylist.message != null }
            assertEquals(LoadError.SERVER, failed.newPlaylist.message)
            assertNull(failed.newPlaylist.created)
            viewModel.dismissMessage()
            viewModel.state.awaitFirst { it.newPlaylist.message == null }
            Unit
        }

        @Test
        fun `a long list is queued as a stretch around the song tapped`() {
            val songs = (0 until 2_000).map { tile(it) }

            val (queue, at) = queueWindow(songs, 1_000)
            assertEquals(500, queue.size)
            assertEquals(songs[1_000], queue[at])

            val (first, start) = queueWindow(songs.take(3), 1)
            assertEquals(3, first.size)
            assertEquals(1, start)
        }
    }

    @Nested
    inner class Favourites {
        private fun viewModel() =
            FavouritesViewModel(connectedApi(server), catalog.repository, catalog.sync)
                .also { created += it }

        @Test
        fun `favourites come from the catalog, with no connection too`() = runBlocking {
            catalog.synced()
            catalog.server.dispatcher.override("ut/v1/me") { dropConnection() }
            val viewModel = viewModel()

            val content = viewModel.state.awaitReady()
            assertEquals(listOf("Lighthouse Keeper"), content.songs.map { it.title })
            assertEquals(listOf("Salt & Ember"), content.albums.map { it.title })
            assertTrue(content.artists.isEmpty())
            assertFalse(content.isEmpty)

            viewModel.refresher.refresh()
            viewModel.refresher.state.awaitFirst { it.error == LoadError.NETWORK }
            assertEquals(content, viewModel.state.awaitReady())
            assertEquals(0, server.requestCount)
        }
    }

    @Nested
    inner class Downloads {
        @Test
        fun `before offline downloads exist the list is empty`() = runTest {
            val viewModel = DownloadsViewModel(NoOfflineDownloads)

            assertEquals(emptyList<TrackTile>(), viewModel.state.awaitReady())
        }

        @Test
        fun `downloads follow the offline library`() = runTest {
            val track = TrackTile(SongId("song-1"), "Invented", "Someone", null, 100, null, false)
            val downloads = MutableStateFlow(emptyList<TrackTile>())
            val viewModel = DownloadsViewModel(
                object : OfflineLibrary {
                    override val downloads = downloads
                }
            )
            assertEquals(emptyList<TrackTile>(), viewModel.state.awaitReady())

            downloads.value = listOf(track)

            assertEquals(
                listOf(track),
                (
                    viewModel.state.awaitFirst {
                        (it as? LoadState.Ready)?.value?.isNotEmpty() == true
                    } as LoadState.Ready
                    ).value
            )
        }
    }
}
