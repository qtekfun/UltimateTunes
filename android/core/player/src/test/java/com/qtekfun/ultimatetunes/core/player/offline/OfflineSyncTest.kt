// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.offline

import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.Album
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.CoverArtId
import com.qtekfun.ultimatetunes.core.api.model.Playlist
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.api.model.RequestReason
import com.qtekfun.ultimatetunes.core.api.model.Song
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.api.model.TrackState
import com.qtekfun.ultimatetunes.core.api.model.TrackStatus
import com.qtekfun.ultimatetunes.core.player.PlayableTrack
import io.mockk.coEvery
import io.mockk.every
import io.mockk.mockk
import java.io.File
import java.io.IOException
import java.nio.file.Path
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir

private fun lib(n: Int) = SongId("0190a5c8-0000-7000-8000-%012d".format(n))
private fun yt(c: Char) = SongId("yt:" + c.toString().repeat(11))
private fun track(id: SongId) = PlayableTrack(id, "Song $id", "Artist")

class OfflineSyncPlannerTest {
    @Test
    fun `kept songs and collection members are downloaded once each`() {
        val selection = OfflineSelection(
            tracks = listOf(track(lib(1))),
            collections = listOf(
                OfflineCollection(
                    CollectionKind.ALBUM,
                    "al",
                    "A",
                    listOf(track(lib(1)), track(lib(2)))
                ),
                OfflineCollection(CollectionKind.PLAYLIST, "pl", "P", listOf(track(lib(3))))
            )
        )
        val plan = OfflineSyncPlanner.plan(selection, downloaded = setOf(lib(2)))
        assertEquals(listOf(lib(1), lib(3)), plan.add.map { it.id })
        assertTrue(plan.remove.isEmpty())
        assertTrue(plan.complete)
    }

    @Test
    fun `songs no longer wanted are removed`() {
        val selection = OfflineSelection(tracks = listOf(track(lib(1))))
        val plan = OfflineSyncPlanner.plan(selection, downloaded = setOf(lib(1), lib(9)))
        assertEquals(setOf(lib(9)), plan.remove)
        assertTrue(plan.add.isEmpty())
    }

    @Test
    fun `yt songs download under their library id once archived, else wait`() {
        val selection = OfflineSelection(
            tracks = listOf(track(yt('A')), track(yt('B')), track(lib(5))),
            aliases = mapOf(yt('A') to lib(5))
        )
        val plan = OfflineSyncPlanner.plan(selection, downloaded = emptySet())
        // yt:A became lib(5), which is also kept on its own: one download.
        assertEquals(listOf(lib(5)), plan.add.map { it.id })
        assertEquals(listOf(yt('B')), plan.awaitingServer)
    }

    @Test
    fun `nothing is removed while a collection was never read`() {
        val selection = OfflineSelection(
            collections = listOf(OfflineCollection(CollectionKind.PLAYLIST, "pl", "P"))
        )
        val plan = OfflineSyncPlanner.plan(selection, downloaded = setOf(lib(1)))
        assertFalse(plan.complete)
        assertTrue(plan.remove.isEmpty())
    }

    @Test
    fun `selection helpers`() {
        val selection = OfflineSelection(
            tracks = listOf(track(lib(1))),
            collections = listOf(OfflineCollection(CollectionKind.ALBUM, "al", "A"))
        )
        assertTrue(selection.keepsTrack(lib(1)))
        assertFalse(selection.keepsTrack(lib(2)))
        assertTrue(selection.keepsCollection(CollectionKind.ALBUM, "al"))
        assertFalse(selection.keepsCollection(CollectionKind.PLAYLIST, "al"))
        assertFalse(selection.isEmpty)
        assertTrue(OfflineSelection().isEmpty)
        assertFalse(OfflineSelection(collections = selection.collections).isEmpty)
    }
}

class OfflineSyncerTest {
    private class MemoryStore(initial: OfflineSelection) : OfflineSelectionStore {
        val state = MutableStateFlow(initial)
        override val selection = state

        override suspend fun update(transform: (OfflineSelection) -> OfflineSelection) {
            state.value = transform(state.value)
        }
    }

    private class MemoryQueue(val ids: MutableSet<SongId>) : DownloadQueue {
        val added = mutableListOf<PlayableTrack>()
        val removed = mutableListOf<SongId>()

        override suspend fun knownIds(): Set<SongId> = ids.toSet()

        override suspend fun add(track: PlayableTrack) {
            added += track
            ids += track.id
        }

        override suspend fun remove(id: SongId) {
            removed += id
            ids -= id
        }
    }

    private val api = mockk<TunesApi> {
        every { coverArtUrl(any(), any()) } returns
            "https://music.example/rest/getCoverArt".toHttpUrl()
    }

    private fun status(id: SongId, state: TrackState, trackId: SongId? = null) =
        TunesResult.Success(TrackStatus(id, trackId, state, 1.0, 1, 3, streamable = true))

    @Test
    fun `a sync reads collections, resolves yt songs and applies the plan`() = runTest {
        val store = MemoryStore(
            OfflineSelection(
                tracks = listOf(track(yt('A')), track(yt('B'))),
                collections = listOf(
                    OfflineCollection(CollectionKind.ALBUM, "al", "Album"),
                    OfflineCollection(CollectionKind.PLAYLIST, "pl", "List", listOf(track(lib(7))))
                )
            )
        )
        val queue = MemoryQueue(mutableSetOf(lib(9)))
        coEvery { api.album(AlbumId("al")) } returns TunesResult.Success(
            Album(
                AlbumId("al"),
                "Album",
                song = listOf(Song(lib(1), "One", duration = 61, coverArt = CoverArtId("al-1")))
            )
        )
        coEvery { api.playlist(PlaylistId("pl")) } returns
            TunesResult.Success(
                Playlist(PlaylistId("pl"), "List", entry = listOf(Song(lib(2), "Two")))
            )
        coEvery { api.requestTrack(yt('A'), RequestReason.KEEP) } returns
            status(yt('A'), TrackState.READY, lib(3))
        coEvery { api.requestTrack(yt('B'), RequestReason.KEEP) } returns
            status(yt('B'), TrackState.DOWNLOADING)

        val plan = OfflineSyncer(api, store, queue).sync()

        assertEquals(setOf(lib(1), lib(2), lib(3)), queue.added.map { it.id }.toSet())
        assertEquals(listOf(lib(9)), queue.removed)
        assertEquals(listOf(yt('B')), plan.awaitingServer)
        val saved = store.state.value
        assertEquals(mapOf(yt('A') to lib(3)), saved.aliases)
        assertEquals(listOf(lib(1)), saved.collections[0].members?.map { it.id })
        assertEquals(listOf(lib(2)), saved.collections[1].members?.map { it.id })
        assertEquals(61_000L, saved.collections[0].members?.single()?.durationMs)
    }

    @Test
    fun `an unreadable collection keeps its last songs, and failed requests wait`() = runTest {
        val store = MemoryStore(
            OfflineSelection(
                tracks = listOf(track(yt('C'))),
                collections = listOf(
                    OfflineCollection(CollectionKind.PLAYLIST, "pl", "List", listOf(track(lib(7))))
                )
            )
        )
        val queue = MemoryQueue(mutableSetOf(lib(7)))
        coEvery { api.playlist(any()) } returns TunesResult.NetworkError(IOException("off"))
        coEvery { api.requestTrack(any(), any()) } returns
            TunesResult.NetworkError(IOException("off"))

        val plan = OfflineSyncer(api, store, queue).sync()

        assertTrue(plan.add.isEmpty())
        assertTrue(plan.remove.isEmpty())
        assertEquals(listOf(yt('C')), plan.awaitingServer)
        assertEquals(listOf(lib(7)), store.state.value.collections.single().members?.map { it.id })
    }

    @Test
    fun `ready without a new id, and known aliases, are not asked again`() = runTest {
        val store = MemoryStore(
            OfflineSelection(
                tracks = listOf(track(yt('D')), track(yt('E'))),
                aliases = mapOf(yt('E') to lib(4))
            )
        )
        coEvery { api.requestTrack(yt('D'), RequestReason.KEEP) } returns
            status(yt('D'), TrackState.READY, yt('D'))
        val queue = MemoryQueue(mutableSetOf())

        OfflineSyncer(api, store, queue).sync()

        assertEquals(listOf(lib(4)), queue.added.map { it.id })
    }

    @Test
    fun `a collection removed during the sync stays removed`() = runTest {
        val store = MemoryStore(
            OfflineSelection(
                collections = listOf(OfflineCollection(CollectionKind.ALBUM, "al", "A"))
            )
        )
        coEvery { api.album(any()) } coAnswers {
            store.state.value = OfflineSelection()
            TunesResult.Success(Album(AlbumId("al"), "A", song = listOf(Song(lib(1), "One"))))
        }
        val queue = MemoryQueue(mutableSetOf())

        OfflineSyncer(api, store, queue).sync()

        assertTrue(store.state.value.collections.isEmpty())
        assertTrue(queue.added.isEmpty())
    }

    @Test
    fun `prune frees dropped songs without the network`() = runTest {
        val store = MemoryStore(OfflineSelection(tracks = listOf(track(lib(1)))))
        val queue = MemoryQueue(mutableSetOf(lib(1), lib(2)))
        val removed = OfflineSyncer(api, store, queue).prune()
        assertEquals(setOf(lib(2)), removed)
        assertEquals(setOf(lib(1)), queue.ids)
    }
}

class DataStoreOfflineSelectionTest {
    @TempDir
    lateinit var dir: Path

    @Test
    fun `the selection survives a round trip and junk reads as empty`() = runTest {
        val dataStore = PreferenceDataStoreFactory.create(scope = backgroundScope) {
            File(dir.toFile(), "sel.preferences_pb")
        }
        val store = DataStoreOfflineSelection(dataStore)
        assertTrue(store.selection.first().isEmpty)

        store.update {
            it.copy(
                tracks = listOf(track(lib(1))),
                collections = listOf(OfflineCollection(CollectionKind.ALBUM, "al", "A")),
                aliases = mapOf(yt('A') to lib(2))
            )
        }
        val read = store.selection.first()
        assertEquals(listOf(lib(1)), read.tracks.map { it.id })
        assertEquals("A", read.collections.single().name)
        assertEquals(mapOf(yt('A') to lib(2)), read.aliases)

        dataStore.edit { it[stringPreferencesKey("offline_selection")] = "{not json" }
        assertTrue(store.selection.first().isEmpty)
    }
}
