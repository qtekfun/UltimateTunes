// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.library

import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.ui.MainDispatcherExtension
import com.qtekfun.ultimatetunes.ui.awaitFirst
import com.qtekfun.ultimatetunes.ui.awaitLoaded
import com.qtekfun.ultimatetunes.ui.awaitReady
import com.qtekfun.ultimatetunes.ui.connectedApi
import com.qtekfun.ultimatetunes.ui.dropConnection
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.subsonicOk
import kotlinx.coroutines.flow.MutableStateFlow
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
class LibraryViewModelsTest {
    private lateinit var server: FakeTunesServer

    @BeforeEach
    fun setUp() {
        server = FakeTunesServer().start()
    }

    @AfterEach
    fun tearDown() {
        server.close()
    }

    /** `count` invented albums for getAlbumList2, named from [first]. */
    private fun albums(count: Int, first: Int = 0): String = (first until first + count)
        .joinToString(",", prefix = "{\"album\":[", postfix = "]}") {
            """{"id":"album-$it","name":"Album $it","artist":"Invented"}"""
        }

    @Nested
    inner class Library {
        @Test
        fun `recently added asks for the newest albums`() = runTest {
            val albums = LibraryViewModel(connectedApi(server)).recentlyAdded.awaitReady()

            val request = server.takeRequest()
            assertEquals("newest", request.url.queryParameter("type"))
            assertEquals(
                LibraryViewModel.RECENT_COUNT.toString(),
                request.url.queryParameter("size")
            )
            assertEquals(
                listOf("Low Orbit", "Salt & Ember", "Harbour Lights"),
                albums.map {
                    it.title
                }
            )
        }

        @Test
        fun `a failure keeps the menu usable and can be retried`() = runTest {
            server.dispatcher.override("rest/getAlbumList2") { dropConnection() }
            val viewModel = LibraryViewModel(connectedApi(server))
            assertEquals(LoadState.Failed(LoadError.NETWORK), viewModel.recentlyAdded.awaitLoaded())

            server.dispatcher.clearOverrides()
            viewModel.load()
            assertEquals(3, viewModel.recentlyAdded.awaitReady().size)
        }
    }

    @Nested
    inner class Artists {
        @Test
        fun `artists come under their index letters`() = runTest {
            val sections = ArtistsViewModel(connectedApi(server)).state.awaitReady()

            assertEquals(listOf("M", "N", "P"), sections.map { it.letter })
            assertEquals("The Paper Lanterns", sections.last().artists.single().name)
            assertTrue(sections.all { s -> s.artists.all { it.coverUrl != null } })
        }

        @Test
        fun `empty letters are dropped`() = runTest {
            server.dispatcher.override("rest/getArtists") {
                subsonicOk(
                    "artists",
                    """{"index":[{"name":"A","artist":[]},{"name":"B","artist":[{"id":"b","name":"Bee"}]}]}"""
                )
            }
            val sections = ArtistsViewModel(connectedApi(server)).state.awaitReady()

            assertEquals(listOf("B"), sections.map { it.letter })
            assertNull(sections.single().artists.single().coverUrl)
        }

        @Test
        fun `a failure can be retried`() = runTest {
            server.dispatcher.override("rest/getArtists") { dropConnection() }
            val viewModel = ArtistsViewModel(connectedApi(server))
            assertEquals(LoadState.Failed(LoadError.NETWORK), viewModel.state.awaitLoaded())

            server.dispatcher.clearOverrides()
            viewModel.load()
            viewModel.load()
            assertEquals(3, viewModel.state.awaitReady().size)
        }
    }

    @Nested
    inner class Albums {
        @Test
        fun `albums load a page at a time until a short page`() = runTest {
            server.dispatcher.override("rest/getAlbumList2") { request ->
                val offset = request.url.queryParameter("offset")!!.toInt()
                val count = if (offset == 0) AlbumsViewModel.PAGE_SIZE else 5
                subsonicOk("albumList2", albums(count, first = offset))
            }
            val viewModel = AlbumsViewModel(connectedApi(server))

            val first = viewModel.state.awaitFirst { !it.loading }
            assertEquals(AlbumsViewModel.PAGE_SIZE, first.albums.size)
            assertTrue(first.hasMore)
            val request = server.takeRequest()
            assertEquals("alphabeticalByName", request.url.queryParameter("type"))
            assertEquals("0", request.url.queryParameter("offset"))

            viewModel.loadMore()
            val second = viewModel.state.awaitFirst {
                !it.loading &&
                    it.albums.size > first.albums.size
            }
            assertEquals(AlbumsViewModel.PAGE_SIZE + 5, second.albums.size)
            assertFalse(second.hasMore)
            assertEquals(
                AlbumsViewModel.PAGE_SIZE.toString(),
                server.takeRequest().url.queryParameter("offset")
            )

            viewModel.loadMore()
            assertEquals(2, server.requestCount)
        }

        @Test
        fun `a failed page shows an error and the same page is asked again`() = runTest {
            server.dispatcher.override("rest/getAlbumList2") { dropConnection() }
            val viewModel = AlbumsViewModel(connectedApi(server))

            val failed = viewModel.state.awaitFirst { it.error != null }
            assertEquals(LoadError.NETWORK, failed.error)
            assertFalse(failed.loading)

            server.dispatcher.override("rest/getAlbumList2") { subsonicOk("albumList2", albums(2)) }
            viewModel.loadMore()
            val loaded = viewModel.state.awaitFirst { it.albums.isNotEmpty() }
            assertNull(loaded.error)
            assertEquals(listOf("Album 0", "Album 1"), loaded.albums.map { it.title })
        }
    }

    @Nested
    inner class Favourites {
        @Test
        fun `favourites list starred songs, albums and artists`() = runTest {
            val viewModel = FavouritesViewModel(connectedApi(server))
            assertEquals(LoadState.Loading, viewModel.state.value)
            viewModel.load()

            val content = viewModel.state.awaitReady()
            assertEquals("/rest/getStarred2", server.takeRequest().url.encodedPath)
            assertEquals(listOf("Lighthouse Keeper"), content.songs.map { it.title })
            assertEquals(listOf("Salt & Ember"), content.albums.map { it.title })
            assertTrue(content.artists.isEmpty())
            assertFalse(content.isEmpty)
        }

        @Test
        fun `showing again reloads without a spinner, and nothing starred is empty`() = runTest {
            val viewModel = FavouritesViewModel(connectedApi(server))
            viewModel.load()
            viewModel.state.awaitReady()

            server.dispatcher.override("rest/getStarred2") { subsonicOk("starred2", "{}") }
            viewModel.load()

            assertTrue(
                viewModel.state.awaitFirst {
                    (it as? LoadState.Ready)?.value?.isEmpty == true
                } is LoadState.Ready
            )
        }

        @Test
        fun `a failure can be retried`() = runTest {
            server.dispatcher.override("rest/getStarred2") { dropConnection() }
            val viewModel = FavouritesViewModel(connectedApi(server))
            viewModel.load()
            assertEquals(LoadState.Failed(LoadError.NETWORK), viewModel.state.awaitLoaded())
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
