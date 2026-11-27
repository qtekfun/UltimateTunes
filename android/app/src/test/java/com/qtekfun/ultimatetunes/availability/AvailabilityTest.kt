// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.availability

import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.ArtistId
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.player.offline.OfflineItem
import com.qtekfun.ultimatetunes.core.player.offline.OfflineSelection
import com.qtekfun.ultimatetunes.core.player.offline.OfflineState
import com.qtekfun.ultimatetunes.playback.toPlayable
import com.qtekfun.ultimatetunes.ui.FakeCachedSongs
import com.qtekfun.ultimatetunes.ui.FakeConnectivity
import com.qtekfun.ultimatetunes.ui.FakeOfflineControls
import com.qtekfun.ultimatetunes.ui.TestCatalog
import com.qtekfun.ultimatetunes.ui.awaitFirst
import com.qtekfun.ultimatetunes.ui.settings.PlaybackSettings
import com.qtekfun.ultimatetunes.ui.settings.PlaybackSettingsStore
import com.qtekfun.ultimatetunes.ui.tile
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.runBlocking
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

private val KEEPER = SongId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01c001")
private val COPPER = SongId("yt:Rb4Tn8wKx1c")
private val OTHER = SongId("song-9")

class AvailabilityTest {
    private val catalog = TestCatalog()
    private val connectivity = FakeConnectivity()
    private val offline = FakeOfflineControls()
    private val cache = FakeCachedSongs()
    private val offlineOnly = MutableStateFlow(false)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined)

    private val settings = object : PlaybackSettingsStore {
        override val settings = offlineOnly.map { PlaybackSettings(offlineOnly = it) }

        override suspend fun setCacheSizeMb(value: Int) = Unit

        override suspend fun setOfflineOnly(value: Boolean) {
            offlineOnly.value = value
        }

        override suspend fun setDownloadOnWifiOnly(value: Boolean) = Unit

        override suspend fun setLibraryOffline(value: Boolean) = Unit

        override suspend fun setLibraryOfflineLimitMb(value: Int) = Unit
    }

    private fun source() = AvailabilitySource(
        connectivity,
        settings,
        offline,
        cache,
        catalog.repository,
        scope,
        Dispatchers.Unconfined
    )

    @AfterEach
    fun close() {
        scope.cancel()
        catalog.close()
    }

    @Test
    fun `online everything plays, under its own id`() {
        val now = Availability()

        assertFalse(now.onlyPhone)
        assertTrue(now.canPlay(OTHER))
        assertTrue(now.canPlayAlbum(AlbumId("a")))
        assertTrue(now.canPlayArtist(ArtistId("b")))
        assertTrue(now.canPlayPlaylist(PlaylistId("c")))
        assertTrue(now.shows(OTHER))
        assertEquals(listOf(tile(9)), now.playable(listOf(tile(9))))
    }

    @Test
    fun `with no connection what is not on the phone stays shown but cannot play`() {
        val now = Availability(online = false, songs = setOf(KEEPER))

        assertTrue(now.onlyPhone)
        assertTrue(now.canPlay(KEEPER))
        assertFalse(now.canPlay(OTHER))
        assertTrue(now.shows(OTHER))
        assertTrue(now.showsAlbum(AlbumId("a")))
        assertTrue(now.showsArtist(ArtistId("b")))
        assertTrue(now.showsPlaylist(PlaylistId("c")))
        assertFalse(now.canPlayAlbum(AlbumId("a")))
    }

    @Test
    fun `offline mode leaves out what the phone does not hold`() {
        val now = Availability(offlineMode = true, songs = setOf(KEEPER))

        assertTrue(now.shows(KEEPER))
        assertFalse(now.shows(OTHER))
        assertFalse(now.showsAlbum(AlbumId("a")))
        assertFalse(now.showsArtist(ArtistId("b")))
        assertFalse(now.showsPlaylist(PlaylistId("c")))
    }

    @Test
    fun `a yt song plays as the library file it was kept as`() {
        val now =
            Availability(online = false, songs = setOf(OTHER), aliases = mapOf(COPPER to OTHER))
        val external = tile(1).copy(id = COPPER, isExternal = true)

        assertEquals(OTHER, now.phoneId(COPPER))
        assertEquals(OTHER, now.playable(listOf(external)).single().id)
        assertFalse(now.playable(listOf(external)).single().isExternal)
        assertNull(Availability(aliases = mapOf(COPPER to OTHER)).phoneId(COPPER))
    }

    @Test
    fun `downloads, cached songs and aliases make albums, artists and playlists available`() =
        runBlocking {
            catalog.synced()
            val source = source()
            offline.mutableItems.value = listOf(
                OfflineItem(tile(9).toPlayable(), OfflineState.DONE, 100f),
                OfflineItem(tile(8).toPlayable(), OfflineState.DOWNLOADING, 10f)
            )
            offline.mutableSelection.value = OfflineSelection(aliases = mapOf(COPPER to OTHER))

            val aliased = source.availability.awaitFirst {
                OTHER in it.songs &&
                    it.playlists.size == 1
            }
            assertFalse(SongId("song-8") in aliased.songs)
            // The playlist's `yt:` song is the download kept under another id.
            assertTrue(aliased.albums.isEmpty())

            cache.songs = setOf(KEEPER)
            source.refresh()
            val cached = source.availability.awaitFirst {
                KEEPER in it.songs && it.albums.size == 1
            }
            assertEquals(1, cached.artists.size)
        }

    @Test
    fun `the player is told what only the phone can play`() = runBlocking {
        cache.songs = setOf(KEEPER)
        offline.mutableSelection.value = OfflineSelection(aliases = mapOf(COPPER to OTHER))
        offline.mutableItems.value =
            listOf(OfflineItem(tile(9).toPlayable(), OfflineState.DONE, 100f))
        val source = source()
        assertFalse(source.onlyPhone())

        connectivity.online.value = false
        assertTrue(source.onlyPhone())
        connectivity.online.value = true
        offlineOnly.value = true
        source.availability.awaitFirst { it.offlineMode }
        assertTrue(source.onlyPhone())

        val songs = source.songs()
        assertEquals(KEEPER, songs.phoneId(KEEPER))
        assertEquals(OTHER, songs.phoneId(COPPER))
        assertNull(songs.phoneId(SongId("song-7")))
    }
}
