// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.offline

import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.model.Song
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.player.PlayableTrack
import com.qtekfun.ultimatetunes.core.player.PlayerSettings
import com.qtekfun.ultimatetunes.core.player.PlayerSettingsSource
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertSame
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class OfflineManagerTest {
    private val songA = SongId("0190a5c8-0000-7000-8000-00000000000a")
    private val songB = SongId("0190a5c8-0000-7000-8000-00000000000b")

    private val store = object : OfflineSelectionStore {
        val state = MutableStateFlow(OfflineSelection())
        override val selection = state

        override suspend fun update(transform: (OfflineSelection) -> OfflineSelection) {
            state.value = transform(state.value)
        }
    }
    private val downloaded = mutableSetOf(songB)
    private val removed = mutableListOf<SongId>()
    private val items = MutableStateFlow<List<OfflineItem>>(emptyList())
    private val queue = object : DownloadQueue {
        override suspend fun knownIds(): Set<SongId> = downloaded.toSet()

        override suspend fun failedIds(): Set<SongId> = emptySet()

        override suspend fun add(track: PlayableTrack) = Unit

        override suspend fun remove(id: SongId) {
            removed += id
            downloaded -= id
        }
    }
    private val downloads = mockk<OfflineDownloads> {
        every { this@mockk.items } returns this@OfflineManagerTest.items
    }
    private val scheduler = mockk<OfflineSyncScheduler>(relaxed = true)
    private val settings = object : PlayerSettingsSource {
        override val settings = MutableStateFlow(PlayerSettings(downloadOnWifiOnly = false))
    }
    private val manager = OfflineManager(
        store,
        downloads,
        OfflineSyncer(mockk<TunesApi>(), store, queue, settings),
        scheduler,
        settings
    )

    @Test
    fun `keeping songs and collections schedules a sync, once each`() = runTest {
        val track = PlayableTrack(songA, "A", "Artist")
        manager.keepTrack(track)
        manager.keepTrack(track)
        manager.keepCollection(CollectionKind.PLAYLIST, "pl", "List")
        manager.keepCollection(CollectionKind.PLAYLIST, "pl", "List")

        val selection = manager.selection.first()
        assertEquals(listOf(track), selection.tracks)
        assertEquals(1, selection.collections.size)
        verify(exactly = 4) { scheduler.schedule(false) }
        // Not wanted any more: freed at once.
        assertEquals(listOf(songB), removed)
        assertSame(items, manager.items)
    }

    @Test
    fun `dropping everything frees the downloads and stops the periodic sync`() = runTest {
        downloaded += songA
        manager.keepTrack(PlayableTrack(songA, "A", "Artist"))
        manager.keepCollection(CollectionKind.ALBUM, "al", "Album")
        removed.clear()

        manager.dropCollection(CollectionKind.ALBUM, "al")
        manager.dropTrack(songA)

        assertTrue(store.state.value.isEmpty)
        assertTrue(songA in removed)
        verify { scheduler.cancel() }
    }

    @Test
    fun `a dropped song is freed even while a kept playlist was never read`() = runTest {
        downloaded += songA
        store.state.value = OfflineSelection(
            tracks = listOf(PlayableTrack(songA, "A", "Artist")),
            collections = listOf(OfflineCollection(CollectionKind.PLAYLIST, "pl", "List"))
        )

        manager.dropTrack(songA)

        assertEquals(listOf(songA), removed)
        // songB is not known to be unwanted (the playlist may have it): kept.
        assertTrue(songB in downloaded)
    }

    @Test
    fun `dropping a read album frees its songs while another list is unread`() = runTest {
        downloaded += songA
        store.state.value = OfflineSelection(
            collections = listOf(
                OfflineCollection(
                    CollectionKind.ALBUM,
                    "al",
                    "Album",
                    listOf(PlayableTrack(songA, "A", "Artist"))
                ),
                OfflineCollection(CollectionKind.PLAYLIST, "pl", "List")
            )
        )

        manager.dropCollection(CollectionKind.ALBUM, "al")

        assertEquals(listOf(songA), removed)
        assertEquals(1, store.state.value.collections.size)
    }

    @Test
    fun `turning the library setting on keeps it pending and schedules a sync`() = runTest {
        settings.settings.value = PlayerSettings(libraryOffline = true, downloadOnWifiOnly = false)

        manager.libraryOfflineChanged()

        val library = manager.library.first()
        assertEquals(LibraryOffline(), library)
        // The library was never read: the download nothing knows about stays.
        assertTrue(removed.isEmpty())
        verify { scheduler.schedule(false) }
        // Turned on again (or the limit changed): what was read is kept until the next sync.
        store.state.value = OfflineSelection(
            library = LibraryOffline(songs = listOf(PlayableTrack(songA, "A", "Artist")))
        )
        manager.libraryOfflineChanged()
        assertEquals(listOf(songA), manager.library.first()?.songs?.map { it.id })
    }

    @Test
    fun `turning it off frees what only the library kept and stops the sync`() = runTest {
        val explicit = PlayableTrack(songA, "A", "Artist")
        val onlyLibrary = PlayableTrack(songB, "B", "Artist")
        downloaded += songA
        store.state.value = OfflineSelection(
            tracks = listOf(explicit),
            library = LibraryOffline(songs = listOf(explicit, onlyLibrary))
        )
        settings.settings.value = PlayerSettings(libraryOffline = false)

        manager.libraryOfflineChanged()

        assertEquals(listOf(songB), removed)
        assertTrue(songA in downloaded)
        assertNull(manager.library.first())
        assertEquals(listOf(explicit), store.state.value.tracks)
        // Something is still kept explicitly: the periodic sync goes on.
        verify { scheduler.schedule(true) }
    }

    @Test
    fun `turning it off with nothing else kept cancels the periodic sync`() = runTest {
        store.state.value = OfflineSelection(
            library = LibraryOffline(songs = listOf(PlayableTrack(songB, "B", "Artist")))
        )
        settings.settings.value = PlayerSettings(libraryOffline = false)

        manager.libraryOfflineChanged()

        assertEquals(listOf(songB), removed)
        verify { scheduler.cancel() }
    }

    @Test
    fun `turning it off frees its songs even while a playlist was never read`() = runTest {
        store.state.value = OfflineSelection(
            collections = listOf(OfflineCollection(CollectionKind.PLAYLIST, "pl", "List")),
            library = LibraryOffline(songs = listOf(PlayableTrack(songB, "B", "Artist")))
        )
        settings.settings.value = PlayerSettings(libraryOffline = false)

        manager.libraryOfflineChanged()

        assertEquals(listOf(songB), removed)
    }

    @Test
    fun `the library can be scanned and fitted to a limit without the setting`() = runTest {
        store.state.value = OfflineSelection(tracks = listOf(PlayableTrack(songA, "A", "Artist")))
        val scan = LibraryScan(
            listOf(
                Song(songA, "A", size = 10 * 1024 * 1024L),
                Song(songB, "B", size = 10 * 1024 * 1024L)
            )
        )

        val report = manager.libraryReport(scan, limitBytes = 5 * 1024 * 1024L)

        // A is kept explicitly: only B counts, and it does not fit.
        assertEquals(1, report.totalCount)
        assertEquals(1, report.leftOutCount)
    }
}
