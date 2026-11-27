// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library

import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.model.ApiKeySecret
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Test

/** Who the catalog is shown to, a clear that fails, and a library that changes while read. */
class CatalogOwnershipTest {
    private val harness = CatalogHarness(pageSize = 10)
    private val remote = harness.remote
    private val repository = harness.repository
    private val songs = (10 until 35).map { song("s$it", "Song $it") }

    @AfterEach
    fun close() = harness.close()

    private fun sync() = runBlocking {
        remote.songs = songs
        remote.playlists = listOf(playlist("p1", "Mine", songs.take(2)))
        assertEquals(CatalogSyncResult.Synced, harness.syncer.sync())
    }

    private suspend fun shown() = repository.songs().first().size

    private val connected: ServerConfig get() = harness.server.serverConfig()

    @Test
    fun `nothing is shown with no connection, though the rows are still stored`() = runBlocking {
        sync()

        harness.config.set(null as ServerConfig?)

        assertEquals(0, shown())
        assertEquals(emptyList<Any>(), repository.playlists().first())
        assertNull(repository.playlist(PlaylistId("p1")).first())
        assertEquals(emptyMap<Any, Any>(), repository.playlistSongIds().first())
        assertNull(repository.syncState.first().lastSuccess)

        // The same connection again, with the server not answering: it was already checked.
        remote.failing += "me"
        harness.config.set(connected)
        assertEquals(songs.size, shown())
        assertNotNull(repository.syncState.first().lastSuccess)
    }

    @Test
    fun `another key shows nothing until the server said whose catalog it is`() = runBlocking {
        sync()
        // As after a disconnect whose clear never ran: another account connects.
        val other = ServerConfig(connected.baseUrl, ApiKeySecret("utk_" + "b".repeat(43)))
        remote.failing += "me"
        harness.config.set(other)

        harness.syncer.syncIfStale()
        assertEquals(0, shown())

        remote.failing.clear()
        remote.user = "user-2"
        remote.failing += "search3"
        harness.syncer.syncIfStale()
        assertEquals(0, shown())
    }

    @Test
    fun `a clear that cannot write does not crash`() = runBlocking {
        sync()
        harness.database.close()

        harness.syncer.clear()
    }

    @Test
    fun `a song removed while the library is read does not hide another one`() = runBlocking {
        remote.songs = songs
        var pages = 0
        remote.onRequest = {
            if (it == "search3" && ++pages == 2) remote.songs = songs.drop(1)
        }

        assertEquals(CatalogSyncResult.Synced, harness.syncer.sync())

        // Song 10 was read before it was removed; every other one is there too.
        assertEquals(songs.map { it.id }.toSet(), repository.songs().first().map { it.id }.toSet())
    }
}
