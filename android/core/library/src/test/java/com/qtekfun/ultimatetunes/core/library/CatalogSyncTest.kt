// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library

import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.api.model.Starred
import com.qtekfun.ultimatetunes.core.library.db.PendingChangeEntity
import java.time.Duration
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertInstanceOf
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class CatalogSyncTest {
    private val harness = CatalogHarness(pageSize = 2)
    private val remote = harness.remote
    private val syncer = harness.syncer
    private val repository = harness.repository

    private val first = song("s1", "One")
    private val second = song("s2", "Two")
    private val third = song("s3", "Three")
    private val outside = song("yt:Qx7Lm2pZ0aB", "Not here yet", album = null)

    @AfterEach
    fun close() = harness.close()

    private fun serve() {
        remote.songs = listOf(first, second, third)
        remote.playlists = listOf(playlist("p1", "Mine", listOf(second, first)))
        remote.starred = Starred(song = listOf(third))
    }

    private suspend fun titles() = repository.songs().first().map { it.title }

    private suspend fun state() = repository.syncState.first()

    private suspend fun entries(id: String = "p1") =
        repository.playlist(PlaylistId(id)).first()?.entry?.map { it.id.value }

    private fun pending() =
        PendingChangeEntity(kind = "star", targetId = "s1", payload = "{}", createdAt = 1)

    @Test
    fun `reads every page, playlist and favourite`() = runBlocking {
        serve()

        assertEquals(CatalogSyncResult.Synced, syncer.sync())

        assertEquals(listOf("One", "Three", "Two"), titles())
        assertEquals(listOf("s2", "s1"), entries())
        assertEquals(listOf("s3"), repository.favouriteSongs().first().map { it.id.value })
        assertEquals(listOf("search3:0", "search3:2"), remote.asked.filter { "search3" in it })
        assertEquals(CatalogSyncState(lastSuccess = NOW), state())
    }

    @Test
    fun `reads the examples of the contract`() = runBlocking {
        // The fake answers the same page at any offset: a page size it does not fill.
        CatalogHarness().use { contract ->
            contract.server.dispatcher.clearOverrides()

            assertEquals(CatalogSyncResult.Synced, contract.syncer.sync())

            assertEquals(1, contract.repository.songs().first().size)
            val example = contract.repository.playlists().first().single()
            assertEquals("Sunday Morning", example.name)
            assertEquals(3, contract.repository.playlist(example.id).first()?.entry?.size)
            assertEquals(1, contract.repository.favouriteAlbums().first().size)
        }
    }

    @Test
    fun `a failed call leaves the catalog as it was`() = runBlocking {
        serve()
        syncer.sync()
        remote.songs = listOf(song("s9", "New"), first, second)
        remote.playlists = listOf(playlist("p2", "Other", listOf(first)))
        remote.starred = Starred()

        for (endpoint in listOf("me", "search3:2", "getPlaylists", "getPlaylist", "getStarred2")) {
            remote.failing.clear()
            remote.failing += endpoint
            harness.clock.advance(Duration.ofHours(1))

            val result = syncer.sync()

            assertInstanceOf(CatalogSyncResult.Failed::class.java, result, endpoint)
            assertEquals(listOf("One", "Three", "Two"), titles(), endpoint)
            assertEquals(listOf("s2", "s1"), entries(), endpoint)
            assertEquals(1, repository.favouriteSongs().first().size, endpoint)
            assertEquals(NOW, state().lastSuccess, endpoint)
            val error = state().error as CatalogSyncError.Server
            assertInstanceOf(TunesResult.Failure::class.java, error.failure)
        }

        remote.failing.clear()
        assertEquals(CatalogSyncResult.Synced, syncer.sync())
        assertNull(state().error)
        assertEquals(listOf("New", "One", "Two"), titles())
    }

    @Test
    fun `a listing the database refuses changes nothing`() = runBlocking {
        serve()
        syncer.sync()
        remote.songs = listOf(first)
        val twice = playlist("p2", "Twice", listOf(first))
        remote.playlists = listOf(twice, twice)

        val result = syncer.sync()

        assertEquals(CatalogSyncResult.Failed(CatalogSyncError.Storage), result)
        assertEquals(listOf("One", "Three", "Two"), titles())
        assertEquals(listOf("s2", "s1"), entries())
        assertEquals(CatalogSyncError.Storage, state().error)
    }

    @Test
    fun `an unchanged playlist is not read again`() = runBlocking {
        serve()
        syncer.sync()
        remote.asked.clear()

        syncer.sync()

        assertTrue(remote.asked.none { it.startsWith("getPlaylist:") })
        assertEquals(listOf("s2", "s1"), entries())

        remote.playlists =
            listOf(playlist("p1", "Mine", listOf(third), changed = NOW.plusSeconds(1)))
        syncer.sync()

        assertEquals(listOf("s3"), entries())
    }

    @Test
    fun `a playlist holding songs outside the library is read again`() = runBlocking {
        serve()
        remote.playlists = listOf(playlist("p1", "Mine", listOf(outside)))
        syncer.sync()
        assertEquals(listOf(outside.id.value), entries())
        assertEquals(listOf("One", "Three", "Two"), titles())

        // Archived: a new id, and the playlist's `changed` stays.
        val archived = song("s4", "Not here yet")
        remote.songs += archived
        remote.playlists = listOf(playlist("p1", "Mine", listOf(archived)))
        syncer.sync()

        assertEquals(listOf("s4"), entries())
    }

    @Test
    fun `a playlist whose song left the library is read again`() = runBlocking {
        serve()
        syncer.sync()
        remote.songs = listOf(first, third)
        remote.playlists = listOf(playlist("p1", "Mine", listOf(first)).copy(songCount = 2))
        remote.asked.clear()

        syncer.sync()

        assertTrue("getPlaylist:p1" in remote.asked)
        assertEquals(listOf("s1"), entries())
    }

    @Test
    fun `a playlist deleted since it was listed is left out`() = runBlocking {
        serve()
        val gone = playlist("p2", "Gone", listOf(first))
        remote.playlists += gone
        remote.onRequest = { if (it == "getPlaylist") remote.playlists -= gone }

        assertEquals(CatalogSyncResult.Synced, syncer.sync())

        assertEquals(listOf("Mine"), repository.playlists().first().map { it.name })
    }

    @Test
    fun `syncs again only when the last sync is old`() = runBlocking {
        serve()
        assertEquals(CatalogSyncResult.Synced, syncer.syncIfStale())
        remote.asked.clear()

        harness.clock.advance(CatalogSyncer.MIN_INTERVAL.minusSeconds(1))
        assertEquals(CatalogSyncResult.Fresh, syncer.syncIfStale())
        assertEquals(listOf("me"), remote.asked.toList())

        harness.clock.advance(Duration.ofSeconds(1))
        assertEquals(CatalogSyncResult.Synced, syncer.syncIfStale())

        // The clock went back: do not wait for it to catch up.
        harness.clock.advance(Duration.ofDays(-1))
        assertEquals(CatalogSyncResult.Synced, syncer.syncIfStale())
    }

    @Test
    fun `another user clears the catalog even when the sync then fails`() = runBlocking {
        serve()
        syncer.sync()
        harness.database.queue().add(pending())
        remote.user = "user-2"
        remote.failing += "search3"

        assertInstanceOf(CatalogSyncResult.Failed::class.java, syncer.syncIfStale())

        assertEquals(emptyList<String>(), titles())
        assertEquals(emptyList<String>(), repository.playlists().first().map { it.name })
        assertEquals(emptyList<PendingChangeEntity>(), harness.database.queue().all())
        assertNull(state().lastSuccess)
    }

    @Test
    fun `a new address of the same library keeps the catalog`() = runBlocking {
        serve()
        syncer.sync()
        harness.database.queue().add(pending())
        FakeTunesServer().start().use { other ->
            ServerLibrary(other).failing += "search3"
            harness.config.set(other.serverConfig())

            assertEquals(CatalogSyncResult.Fresh, syncer.syncIfStale())
        }

        assertEquals(listOf("One", "Three", "Two"), titles())
        assertEquals(1, harness.database.queue().all().size)
    }

    @Test
    fun `clearing forgets everything`() = runBlocking {
        serve()
        syncer.sync()
        harness.database.queue().add(pending())

        syncer.clear()

        assertEquals(emptyList<String>(), titles())
        assertEquals(emptyList<String>(), repository.favouriteSongs().first().map { it.title })
        assertEquals(emptyList<PendingChangeEntity>(), harness.database.queue().all())
        assertEquals(CatalogSyncState(), state())
    }

    @Test
    fun `a sync overtaken by a clear stores nothing`() = runBlocking {
        serve()
        remote.onRequest = { if (it == "getStarred2") runBlocking { syncer.clear() } }

        assertEquals(CatalogSyncResult.Discarded, syncer.sync())

        assertEquals(emptyList<String>(), titles())
        assertEquals(CatalogSyncState(), state())
    }

    @Test
    fun `a sync overtaken by a disconnection reports no error`() = runBlocking {
        serve()
        remote.onRequest = { if (it == "search3") harness.config.set(null) }

        assertEquals(CatalogSyncResult.Discarded, syncer.sync())

        assertEquals(emptyList<String>(), titles())
        assertNull(state().error)
    }

    @Test
    fun `nothing read from another server is stored`() = runBlocking {
        serve()
        FakeTunesServer().start().use { other ->
            remote.onRequest = {
                if (it == "getStarred2") harness.config.set(other.serverConfig())
            }

            assertEquals(CatalogSyncResult.Discarded, syncer.sync())
        }

        assertEquals(emptyList<String>(), titles())
    }

    @Test
    fun `without a server nothing happens`() = runBlocking {
        harness.config.set(null as ServerConfig?)

        val result = syncer.sync()

        assertEquals(
            CatalogSyncResult.Failed(CatalogSyncError.Server(TunesResult.NotConfigured)),
            result
        )
        assertTrue(remote.asked.isEmpty())
    }

    @Test
    fun `says that it is syncing while it reads`() = runBlocking {
        serve()
        var during: CatalogSyncState? = null
        remote.onRequest = { if (it == "getStarred2") during = runBlocking { state() } }

        syncer.sync()

        assertEquals(true, during?.syncing)
        assertEquals(false, state().syncing)
    }

    @Test
    fun `two syncs asked at once run one after the other`() = runBlocking {
        serve()

        val results = coroutineScope {
            val one = async { syncer.syncIfStale() }
            val two = async { syncer.syncIfStale() }
            listOf(one.await(), two.await())
        }

        assertEquals(setOf(CatalogSyncResult.Synced, CatalogSyncResult.Fresh), results.toSet())
        assertNotNull(state().lastSuccess)
    }

    @Test
    fun `pending changes stay across syncs, in order`() = runBlocking {
        serve()
        syncer.sync()
        val changes = harness.database.queue()
        val one = changes.add(pending())
        changes.add(pending().copy(kind = "unstar"))

        syncer.sync()

        assertEquals(listOf("star", "unstar"), changes.all().map { it.kind })
        changes.remove(one)
        assertEquals(listOf("unstar"), changes.all().map { it.kind })
    }
}
