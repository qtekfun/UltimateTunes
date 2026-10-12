// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.actions

import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.player.export.ExportReport
import com.qtekfun.ultimatetunes.core.player.export.ExportStatus
import com.qtekfun.ultimatetunes.core.player.offline.OfflineItem
import com.qtekfun.ultimatetunes.core.player.offline.OfflineState
import com.qtekfun.ultimatetunes.playback.toPlayable
import com.qtekfun.ultimatetunes.ui.FakeExports
import com.qtekfun.ultimatetunes.ui.FakeOfflineControls
import com.qtekfun.ultimatetunes.ui.MainDispatcherExtension
import com.qtekfun.ultimatetunes.ui.awaitFirst
import com.qtekfun.ultimatetunes.ui.connectedApi
import com.qtekfun.ultimatetunes.ui.dropConnection
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.LoadState
import com.qtekfun.ultimatetunes.ui.subsonicFailure
import com.qtekfun.ultimatetunes.ui.tile
import kotlinx.coroutines.cancel
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
class LibraryActionsViewModelTest {
    private lateinit var server: FakeTunesServer
    private val offline = FakeOfflineControls()
    private val starredSong = SongId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01c001")
    private val created = mutableListOf<LibraryActionsViewModel>()

    @BeforeEach
    fun setUp() {
        server = FakeTunesServer().start()
    }

    @AfterEach
    fun tearDown() {
        created.forEach { it.viewModelScope.cancel() }
        server.close()
    }

    /** A view model whose favourites have loaded (one request). */
    private suspend fun viewModel(exports: Exports = FakeExports()) =
        LibraryActionsViewModel(connectedApi(server), offline, exports).also { vm ->
            created += vm
            vm.state.awaitFirst { it.favourites.isNotEmpty() }
            server.takeRequest()
        }

    @Test
    fun `favourites load at start and toggle with star and unstar`() = runTest {
        val viewModel = viewModel()
        assertEquals(setOf(starredSong), viewModel.state.value.favourites)

        viewModel.toggleFavourite(tile(3))
        assertTrue(SongId("song-3") in viewModel.state.value.favourites)
        val star = server.takeRequest()
        assertEquals("/rest/star", star.url.encodedPath)
        assertEquals("song-3", star.url.queryParameter("id"))

        viewModel.toggleFavourite(tile(3))
        assertFalse(SongId("song-3") in viewModel.state.value.favourites)
        assertEquals("/rest/unstar", server.takeRequest().url.encodedPath)
    }

    @Test
    fun `a refused favourite is undone and explained`() = runTest {
        server.dispatcher.override("rest/star") { subsonicFailure(50) }
        val viewModel = viewModel()

        viewModel.toggleFavourite(tile(3))

        val failed = viewModel.state.awaitFirst { it.event != null }
        assertEquals(ActionEvent.Failed(LoadError.SERVER), failed.event)
        assertFalse(SongId("song-3") in failed.favourites)
        viewModel.dismissEvent()
        assertNull(viewModel.state.value.event)
    }

    @Test
    fun `refreshing favourites keeps them when the server cannot answer`() = runTest {
        val viewModel = viewModel()
        server.dispatcher.override("rest/getStarred2") { dropConnection() }

        viewModel.refreshFavourites()
        server.takeRequest()

        assertEquals(setOf(starredSong), viewModel.state.value.favourites)
    }

    @Test
    fun `add to playlist lists the user's playlists and adds the songs at the end`() = runTest {
        val viewModel = viewModel()
        val songs = listOf(tile(1), tile(2))

        viewModel.pickPlaylist(songs)
        val picker = viewModel.state.awaitFirst {
            it.picker?.playlists is LoadState.Ready
        }.picker!!
        assertEquals(songs, picker.tracks)
        val playlist = (picker.playlists as LoadState.Ready).value.single()
        assertEquals("Sunday Morning", playlist.name)
        server.takeRequest()

        viewModel.addToPlaylist(playlist)

        assertNull(viewModel.state.value.picker)
        assertEquals(
            ActionEvent.AddedToPlaylist("Sunday Morning", 2),
            viewModel.state.awaitFirst { it.event != null }.event
        )
        val update = server.takeRequest()
        assertEquals("/rest/updatePlaylist", update.url.encodedPath)
        assertEquals(playlist.id.value, update.url.queryParameter("playlistId"))
        assertEquals(listOf("song-1", "song-2"), update.url.queryParameterValues("songIdToAdd"))
    }

    @Test
    fun `add to a new playlist creates it with the songs`() = runTest {
        val viewModel = viewModel()
        viewModel.pickPlaylist(listOf(tile(4)))
        viewModel.state.awaitFirst { it.picker?.playlists is LoadState.Ready }
        server.takeRequest()

        viewModel.createPlaylist("  ")
        assertTrue(viewModel.state.value.picker != null)
        viewModel.createPlaylist(" Road Songs ")

        assertEquals(
            ActionEvent.AddedToPlaylist("Road Songs", 1),
            viewModel.state.awaitFirst { it.event != null }.event
        )
        val create = server.takeRequest()
        assertEquals("/rest/createPlaylist", create.url.encodedPath)
        assertEquals("Road Songs", create.url.queryParameter("name"))
        assertEquals(listOf("song-4"), create.url.queryParameterValues("songId"))
    }

    @Test
    fun `a playlist change that fails is explained, and the picker can be closed`() = runTest {
        server.dispatcher.override("rest/updatePlaylist") { dropConnection() }
        val viewModel = viewModel()
        viewModel.pickPlaylist(emptyList())
        assertNull(viewModel.state.value.picker)

        viewModel.pickPlaylist(listOf(tile(1)))
        val playlist = (
            viewModel.state.awaitFirst {
                it.picker?.playlists is LoadState.Ready
            }.picker!!.playlists as LoadState.Ready
            ).value.single()
        viewModel.addToPlaylist(playlist)
        assertEquals(
            ActionEvent.Failed(LoadError.NETWORK),
            viewModel.state.awaitFirst { it.event != null }.event
        )

        viewModel.pickPlaylist(listOf(tile(1)))
        viewModel.dismissPicker()
        assertNull(viewModel.state.value.picker)
        viewModel.addToPlaylist(playlist)
        viewModel.createPlaylist("Ignored")
    }

    @Test
    fun `a song is kept offline and dropped again`() = runTest {
        val viewModel = viewModel()

        viewModel.toggleDownload(tile(5))
        assertTrue(
            viewModel.state.awaitFirst { SongId("song-5") in it.keptOffline }.event ==
                ActionEvent.Downloading
        )

        viewModel.toggleDownload(tile(5))
        val dropped = viewModel.state.awaitFirst { it.keptOffline.isEmpty() }
        assertEquals(ActionEvent.DownloadRemoved, dropped.event)
    }

    @Test
    fun `finished downloads are known`() = runTest {
        val viewModel = viewModel()
        offline.mutableItems.value = listOf(
            OfflineItem(tile(1).toPlayable(), OfflineState.DONE, 100f),
            OfflineItem(tile(2).toPlayable(), OfflineState.DOWNLOADING, 40f)
        )
        assertEquals(setOf(SongId("song-1")), viewModel.state.value.downloaded)
    }

    @Test
    fun `an export first asks for a folder, then starts with the aliases of yt songs`() = runTest {
        val exports = FakeExports()
        val viewModel = viewModel(exports)
        val external = tile(9, external = true)
        offline.mutableSelection.value = offline.mutableSelection.value.copy(
            aliases = mapOf(external.id to SongId("lib-9"))
        )

        viewModel.export(listOf(tile(1), external, tile(1)))
        assertTrue(viewModel.state.awaitFirst { it.needsFolder }.needsFolder)
        assertTrue(exports.started.isEmpty())

        viewModel.onFolderPicked("content://tree/music")

        assertEquals(
            ActionEvent.ExportStarted(2),
            viewModel.state.awaitFirst {
                it.event != null
            }.event
        )
        assertFalse(viewModel.state.value.needsFolder)
        val (folder, tracks, aliases) = exports.started.single()
        assertEquals("content://tree/music", folder)
        assertEquals(3, tracks.size)
        assertEquals(mapOf(external.id to SongId("lib-9")), aliases)
    }

    @Test
    fun `with a folder already picked the export starts at once`() = runTest {
        val exports = FakeExports(folder = "content://tree/kept")
        val viewModel = viewModel(exports)
        viewModel.export(emptyList())
        assertTrue(exports.started.isEmpty())

        viewModel.export(listOf(tile(1)))

        viewModel.state.awaitFirst { it.event != null }
        assertEquals("content://tree/kept", exports.started.single().first)
    }

    @Test
    fun `a cancelled folder picker exports nothing`() = runTest {
        val exports = FakeExports()
        val viewModel = viewModel(exports)
        viewModel.export(listOf(tile(1)))
        viewModel.state.awaitFirst { it.needsFolder }

        viewModel.onFolderPicked(null)

        assertFalse(viewModel.state.value.needsFolder)
        assertTrue(exports.started.isEmpty())
    }

    @Test
    fun `the export's progress and report follow the exporter`() = runTest {
        val exports = FakeExports()
        val viewModel = viewModel(exports)

        exports.mutableStatus.value = ExportStatus.Running(1, 3)
        assertEquals(ExportStatus.Running(1, 3), viewModel.state.value.export)
        exports.mutableStatus.value = ExportStatus.Finished(ExportReport(3, emptyList()))

        viewModel.dismissExport()
        assertEquals(ExportStatus.Idle, viewModel.state.value.export)
    }

    @Test
    fun `an export while another one runs does not start and says why`() = runTest {
        val exports = FakeExports(folder = "content://tree/kept").apply { busy = true }
        val viewModel = viewModel(exports)

        viewModel.export(listOf(tile(1)))

        assertEquals(ActionEvent.ExportBusy, viewModel.state.awaitFirst { it.event != null }.event)
        assertTrue(exports.started.isEmpty())
    }
}
