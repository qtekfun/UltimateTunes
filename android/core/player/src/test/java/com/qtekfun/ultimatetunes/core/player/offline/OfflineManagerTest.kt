// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.offline

import com.qtekfun.ultimatetunes.core.api.TunesApi
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
        OfflineSyncer(mockk<TunesApi>(), store, queue),
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
}
