// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library

import com.qtekfun.ultimatetunes.core.api.fake.form
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.Playlist
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.api.model.Song
import com.qtekfun.ultimatetunes.core.api.model.SongId
import java.time.Instant
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import mockwebserver3.MockResponse
import mockwebserver3.RecordedRequest
import mockwebserver3.SocketEffect
import okhttp3.Headers.Companion.headersOf
import okhttp3.HttpUrl
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test

/** How the server answers a request instead of serving it. */
private enum class Fault {
    /** The connection drops before anything is done. */
    OFFLINE,

    /** It is done, and the answer is lost. */
    LOST_ANSWER,
    REFUSED,
    BROKEN
}

/** A server that keeps what is written to it, as the real one does. */
private class WritableServer(private val harness: CatalogHarness) {
    private val remote = harness.remote
    val songs = (1..1500).map { song("s$it", "Song $it") }.associateBy { it.id.value }
    val writes = mutableListOf<String>()
    val plays = mutableListOf<Pair<String, Long>>()
    val starred = mutableSetOf<String>()

    /** `yt:` songs archived under a library id. */
    val archived = mutableMapOf<String, String>()
    var fault: (String) -> Fault? = { null }
    private var made = 0

    /** Songs the server does not know: a write naming one is refused whole. */
    val unknown = mutableSetOf<String>()

    /** Runs while a request is being answered. */
    var during: (String) -> Unit = {}

    init {
        write("createPlaylist") { form ->
            val id = form.queryParameter("playlistId") ?: "new-${++made}"
            val songs = form.queryParameterValues("songId").map { known(it!!) }
            val old = find(id)
            check(songs.size <= 1000)
            put(playlist(id, old?.name ?: form.queryParameter("name")!!, songs), old)
            "playlist" to Json.encodeToJsonElement(Playlist.serializer(), find(id)!!)
        }
        write("updatePlaylist") { form ->
            val old = find(form.queryParameter("playlistId")!!) ?: return@write null
            val removed = form.queryParameterValues("songIndexToRemove").map {
                it!!.toInt()
            }.toSet()
            val added = form.queryParameterValues("songIdToAdd").map { known(it!!) }
            check(removed.size + added.size <= 1000)
            val songs = old.entry.filterIndexed { i, _ -> i !in removed } + added
            put(playlist(old.id.value, form.queryParameter("name") ?: old.name, songs), old)
            null to null
        }
        write("deletePlaylist") { query ->
            val old = find(query.queryParameter("id")!!) ?: return@write null
            remote.playlists -= old
            null to null
        }
        write("star") { query ->
            starred += query.queryParameterValues("id").filterNotNull()
            starred += query.queryParameterValues("albumId").filterNotNull()
            null to null
        }
        write("unstar") { query ->
            starred -= query.queryParameterValues("id").filterNotNull().toSet()
            starred -= query.queryParameterValues("albumId").filterNotNull().toSet()
            null to null
        }
        write("scrobble") { query ->
            plays += query.queryParameter("id")!! to query.queryParameter("time")!!.toLong()
            null to null
        }
        write("getSong") { query ->
            val id = query.queryParameter("id")!!
            val found = known(archived[id] ?: id)
            val last = plays.filter { it.first == id }.maxOfOrNull { it.second }
            val song = found.copy(played = last?.let(Instant::ofEpochMilli))
            "song" to Json.encodeToJsonElement(Song.serializer(), song)
        }
    }

    fun known(id: String): Song = songs[id] ?: song(id, "Other $id", album = null)

    fun find(id: String) = remote.playlists.firstOrNull { it.id.value == id }

    fun created(id: String, at: Instant) {
        val old = find(id)!!
        remote.playlists = remote.playlists - old + old.copy(created = at)
    }

    fun ids(id: String) = find(id)!!.entry.map { it.id.value }

    fun set(id: String, name: String, vararg songs: String) {
        put(playlist(id, name, songs.map(::known)), find(id))
    }

    private fun put(new: Playlist, old: Playlist?) {
        val changed = (old?.changed ?: NOW).plusSeconds(1)
        remote.playlists =
            remote.playlists.filterNot { it.id == new.id } + new.copy(changed = changed)
    }

    /** Serves `rest/<name>`; [handle] returns null for "not found". */
    private fun write(name: String, handle: (HttpUrl) -> Pair<String?, JsonElement?>?) {
        harness.server.dispatcher.override("rest/$name") { request: RecordedRequest ->
            val query = if (request.method == "POST") request.form() else request.url
            if (name != "getSong") writes += name
            during(name)
            val named = query.queryParameterValues("songId") +
                query.queryParameterValues("songIdToAdd")
            if (named.any { it in unknown }) return@override failed(70)
            when (fault(name)) {
                Fault.OFFLINE -> dropped()

                Fault.REFUSED -> failed(50)

                Fault.BROKEN -> MockResponse(code = 500)

                Fault.LOST_ANSWER -> {
                    handle(query)
                    dropped()
                }

                null -> handle(query)?.let { (key, value) -> ok(key, value) } ?: failed(70)
            }
        }
    }

    private fun dropped() =
        MockResponse.Builder().onResponseStart(SocketEffect.CloseSocket()).build()

    private fun json(body: String) = MockResponse(
        code = 200,
        headers = headersOf("Content-Type", "application/json"),
        body = body
    )

    private fun ok(key: String?, value: JsonElement?): MockResponse {
        val field = if (key == null) "" else ""","$key":$value"""
        return json("""{"subsonic-response":{"status":"ok"$field}}""")
    }

    private fun failed(code: Int) =
        json("""{"subsonic-response":{"status":"failed","error":{"code":$code}}}""")
}

class OfflineChangesTest {
    private val harness = CatalogHarness()
    private val server = WritableServer(harness)
    private val changes: OfflineChanges = DefaultOfflineChanges(harness.syncer, harness.clock)
    private val repository = harness.repository

    @BeforeEach
    fun setUp() = runBlocking<Unit> {
        harness.remote.songs = (1..5).map { server.known("s$it") }
        server.set("p1", "Mix", "s1", "s2", "s3")
        assertEquals(CatalogSyncResult.Synced, harness.syncer.sync())
    }

    @AfterEach
    fun tearDown() = harness.close()

    private fun offline() {
        server.fault = { Fault.OFFLINE }
    }

    private fun online() {
        server.fault = { null }
    }

    private suspend fun stored(id: String = "p1") = repository.playlist(PlaylistId(id)).first()

    private suspend fun storedIds(id: String = "p1") = stored(id)!!.entry.map { it.id.value }

    private suspend fun p1() = stored()!!

    private suspend fun waiting() = changes.status.first().count

    private suspend fun add(vararg songs: String, to: String = "p1") {
        assertTrue(changes.addToPlaylist(stored(to)!!, songs.map(server::known)))
    }

    @Test
    fun `edits show at once with no connection and reach the server later`() = runBlocking<Unit> {
        offline()
        changes.renamePlaylist(p1(), "Evening")
        add("s4")
        changes.removeFromPlaylist(p1(), 0)
        changes.reorderPlaylist(p1(), listOf("s4", "s2", "s3").map(::SongId))

        assertEquals("Evening", p1().name)
        assertEquals(listOf("s4", "s2", "s3"), storedIds())
        assertEquals(3, p1().songCount)
        assertEquals(300, p1().duration)
        assertEquals(setOf(PlaylistId("p1")), changes.status.first().playlists)
        assertEquals(SendResult(waiting = true), changes.send())
        assertEquals(4, waiting())

        online()
        assertEquals(SendResult(changed = true), changes.send())

        assertEquals("Evening", server.find("p1")!!.name)
        assertEquals(listOf("s4", "s2", "s3"), server.ids("p1"))
        assertEquals(0, waiting())
    }

    @Test
    fun `changes are applied over what another device did, by song and not by position`() =
        runBlocking<Unit> {
            changes.removeFromPlaylist(p1(), 1)
            add("s4")
            server.set("p1", "Mix", "s5", "s1", "s2", "s3")

            changes.send()

            assertEquals(listOf("s5", "s1", "s3", "s4"), server.ids("p1"))
        }

    @Test
    fun `a sync keeps what is still waiting, and sends it first when it can`() = runBlocking<Unit> {
        add("s4")
        server.set("p1", "Mix", "s1", "s2", "s3", "s5")
        server.fault = { if (it == "createPlaylist") Fault.BROKEN else null }

        assertEquals(CatalogSyncResult.Synced, harness.syncer.sync())

        assertEquals(listOf("s1", "s2", "s3", "s5", "s4"), storedIds())
        assertEquals(1, waiting())

        online()
        assertEquals(CatalogSyncResult.Synced, harness.syncer.syncIfStale())
        assertEquals(listOf("s1", "s2", "s3", "s5", "s4"), server.ids("p1"))
        assertEquals(0, waiting())
    }

    @Test
    fun `a playlist deleted on the server drops its changes and says so`() = runBlocking<Unit> {
        add("s4")
        changes.renamePlaylist(p1(), "Evening")
        harness.remote.playlists = emptyList()

        changes.send()

        assertEquals(0, waiting())
        assertNull(stored())
        val notice = changes.notices.first().single()
        assertEquals("Mix" to true, notice.playlist to notice.deletedOnServer)
        changes.dismiss(notice.id)
        assertTrue(changes.notices.first().isEmpty())
    }

    @Test
    fun `a refused change is dropped with a notice and the rest goes on`() = runBlocking<Unit> {
        server.fault = { if (it == "createPlaylist") Fault.REFUSED else null }
        add("s4")
        changes.setSongFavourite(server.known("s1"), true)

        val result = changes.send()

        assertTrue(result.changed)
        assertFalse(result.waiting)
        assertFalse(changes.notices.first().single().deletedOnServer)
        assertEquals(setOf("s1"), server.starred)
    }

    @Test
    fun `a refused favourite has a notice with no playlist`() = runBlocking<Unit> {
        server.fault = { Fault.REFUSED }
        changes.setAlbumFavourite(AlbumId("al1"), true)

        changes.send()

        assertNull(changes.notices.first().single().playlist)
        assertEquals(0, waiting())
    }

    @Test
    fun `a write whose answer is lost is not done twice`() = runBlocking<Unit> {
        add("s4", "s1")
        server.fault = { if (it == "createPlaylist") Fault.LOST_ANSWER else null }
        changes.send()
        assertEquals(1, server.writes.count { it == "createPlaylist" })

        online()
        changes.send()

        assertEquals(listOf("s1", "s2", "s3", "s4", "s1"), server.ids("p1"))
        assertEquals(0, waiting())
    }

    @Test
    fun `a playlist made offline is made once, even if the answer is lost`() = runBlocking<Unit> {
        server.set("old", "New", "s5")
        offline()
        val local = changes.createPlaylist("New", listOf(server.known("s1")))!!
        assertTrue(local.isLocal)
        assertEquals(listOf("s1"), storedIds(local.value))

        server.fault = { if (it == "createPlaylist") Fault.LOST_ANSWER else null }
        changes.send()
        online()
        changes.send()

        assertEquals(
            listOf("old", "new-1", "p1").sorted(),
            harness.remote.playlists.map {
                it.id.value
            }.sorted()
        )
        assertEquals(listOf("s1"), server.ids("new-1"))
        assertEquals(listOf("s5"), server.ids("old"))
        assertEquals(PlaylistId("new-1"), changes.replaced.first()[local])
        assertNull(stored(local.value))
        assertEquals(listOf("s1"), storedIds("new-1"))

        // A screen that still holds the temporary id changes the same playlist.
        changes.addToPlaylist(stored("new-1")!!.copy(id = local), listOf(server.known("s2")))
        changes.send()
        assertEquals(listOf("s1", "s2"), server.ids("new-1"))
    }

    @Test
    fun `a create that never arrived is tried again`() = runBlocking<Unit> {
        changes.createPlaylist("New")
        server.fault = { if (it == "createPlaylist") Fault.OFFLINE else null }
        changes.send()
        online()

        changes.send()

        assertEquals("New", server.find("new-1")!!.name)
        assertEquals(0, waiting())
    }

    @Test
    fun `a playlist made and deleted offline never reaches the server`() = runBlocking<Unit> {
        val local = changes.createPlaylist("New")!!
        changes.deletePlaylist(stored(local.value)!!)
        assertNull(stored(local.value))

        changes.send()

        assertTrue(server.writes.isEmpty())
        assertEquals(0, waiting())
    }

    @Test
    fun `deleting after a lost create deletes what it left`() = runBlocking<Unit> {
        val local = changes.createPlaylist("New")!!
        server.fault = { if (it == "createPlaylist") Fault.LOST_ANSWER else null }
        changes.send()
        online()
        changes.deletePlaylist(Playlist(local, "New"))

        changes.send()

        assertEquals(listOf("p1"), harness.remote.playlists.map { it.id.value })
        assertEquals(0, waiting())
    }

    @Test
    fun `deleting after a create that never arrived does nothing`() = runBlocking<Unit> {
        val local = changes.createPlaylist("New")!!
        server.fault = { if (it == "createPlaylist") Fault.OFFLINE else null }
        changes.send()
        online()
        changes.deletePlaylist(Playlist(local, "New"))

        changes.send()

        assertFalse("deletePlaylist" in server.writes)
        assertEquals(0, waiting())
    }

    @Test
    fun `deleting works offline, and twice is not an error`() = runBlocking<Unit> {
        offline()
        changes.deletePlaylist(p1())
        assertNull(stored())

        server.fault = { if (it == "deletePlaylist") Fault.LOST_ANSWER else null }
        changes.send()
        online()
        changes.send()

        assertNull(server.find("p1"))
        assertEquals(0, waiting())
        assertTrue(changes.notices.first().isEmpty())
    }

    @Test
    fun `a refused delete says so`() = runBlocking<Unit> {
        server.fault = { if (it == "deletePlaylist") Fault.REFUSED else null }
        changes.deletePlaylist(p1())

        changes.send()

        assertEquals("Mix", changes.notices.first().single().playlist)
    }

    @Test
    fun `favourites show at once and the last choice is sent`() = runBlocking<Unit> {
        offline()
        changes.setSongFavourite(server.known("s1"), true)
        changes.setSongFavourite(server.known("s2"), true)
        changes.setSongFavourite(server.known("s2"), true)
        changes.setSongFavourite(server.known("yt:abcdefghijk"), true)
        changes.setSongFavourite(server.known("s1"), false)
        changes.setAlbumFavourite(AlbumId("al1"), true)

        assertEquals(
            listOf("yt:abcdefghijk", "s2"),
            repository.favouriteSongs().first().map { it.id.value }
        )
        assertEquals(mapOf(AlbumId("al1") to true), changes.status.first().albumFavourites)

        online()
        changes.send()
        assertEquals(setOf("s2", "yt:abcdefghijk", "al1"), server.starred)
        assertEquals(1, server.writes.count { it == "unstar" })

        changes.setAlbumFavourite(AlbumId("al1"), false)
        changes.send()
        assertEquals(setOf("s2", "yt:abcdefghijk"), server.starred)
    }

    @Test
    fun `album favourites show in the catalog`() = runBlocking<Unit> {
        harness.remote.songs = listOf(server.known("s1"))
        offline()
        harness.syncer.sync()
        // The library of this fake lists no albums but those of its songs.
        val album = repository.albums().first().single().id
        changes.setAlbumFavourite(album, true)
        changes.setAlbumFavourite(album, true)
        assertEquals(listOf(album), repository.favouriteAlbums().first().map { it.id })

        changes.setAlbumFavourite(album, false)
        assertTrue(repository.favouriteAlbums().first().isEmpty())
    }

    @Test
    fun `plays keep their time and are counted once`() = runBlocking<Unit> {
        offline()
        val first = NOW.minusSeconds(3600)
        changes.scrobble(SongId("s1"), first)
        changes.scrobble(SongId("s1"), NOW)
        assertEquals(2, repository.mostPlayedSongs(1).first().single().playCount)
        changes.send()

        server.fault = { if (it == "scrobble") Fault.LOST_ANSWER else null }
        changes.send()
        online()
        val result = changes.send()

        assertEquals(
            listOf("s1" to first.toEpochMilli(), "s1" to NOW.toEpochMilli()),
            server.plays
        )
        // A play needs no sync of the catalog.
        assertFalse(result.changed)
        assertEquals(0, waiting())
    }

    @Test
    fun `a song archived since it was added is not added twice`() = runBlocking<Unit> {
        val external = "yt:abcdefghijk"
        add(external)
        changes.send()
        server.set("p1", "Mix", "s1", "s2", "s3", "s5")
        server.archived[external] = "s5"
        // The same intention again, as after a lost answer.
        changes.addToPlaylist(Playlist(PlaylistId("p1"), "Mix"), emptyList())
        offline()
        changes.send()
        online()
        changes.removeFromPlaylist(
            Playlist(PlaylistId("p1"), "Mix", entry = listOf(server.known(external))),
            0
        )

        changes.send()

        assertEquals(listOf("s1", "s2", "s3"), server.ids("p1"))
    }

    @Test
    fun `reordering a long playlist loses nothing when it fails midway`() = runBlocking<Unit> {
        val all = (1..1200).map { "s$it" }
        server.set("big", "Big", *all.toTypedArray())
        harness.syncer.sync()
        changes.reorderPlaylist(stored("big")!!, all.reversed().map(::SongId))
        var updates = 0
        server.fault = { if (it == "updatePlaylist" && ++updates == 2) Fault.LOST_ANSWER else null }

        changes.send()
        assertEquals(all.toSet(), server.ids("big").toSet())
        assertEquals(1200, server.ids("big").size)
        assertEquals(1, waiting())

        online()
        changes.send()
        assertEquals(all.reversed(), server.ids("big"))
        assertEquals(0, waiting())
    }

    @Test
    fun `nothing is stored or sent for a catalog that is not this connection's`() =
        runBlocking<Unit> {
            val playlist = p1()
            add("s4")
            harness.config.set(harness.server.serverConfig(apiKey = "utk_other"))

            assertFalse(changes.renamePlaylist(playlist, "No"))
            assertNull(changes.createPlaylist("No"))
            assertEquals(SendResult(waiting = true), changes.send())
            harness.config.set(null)
            assertEquals(SendResult(waiting = true), changes.send())
            assertFalse(changes.scrobble(SongId("s1"), NOW))
            assertTrue(server.writes.isEmpty())

            harness.syncer.clear()
            assertEquals(0, waiting())
        }

    @Test
    fun `changes wait in the database for the next start`() = runBlocking<Unit> {
        offline()
        add("s4")
        changes.send()
        online()

        val restarted = CatalogSyncer(harness.api, harness.database, harness.config, harness.clock)
        DefaultOfflineChanges(restarted, harness.clock).send()

        assertEquals(listOf("s1", "s2", "s3", "s4"), server.ids("p1"))
    }

    private suspend fun lostCreate(name: String): PlaylistId {
        val local = changes.createPlaylist(name)!!
        server.fault = { if (it == "createPlaylist") Fault.OFFLINE else null }
        changes.send()
        online()
        return local
    }

    @Test
    fun `a retried create does not adopt someone else's playlist of the same name`() =
        runBlocking<Unit> {
            lostCreate("New")
            server.set("theirs", "New", "s5")

            changes.send()

            assertEquals(listOf("s5"), server.ids("theirs"))
            assertEquals("New", server.find("new-1")?.name)
        }

    @Test
    fun `deleting after a lost create spares another playlist of the same name`() =
        runBlocking<Unit> {
            val local = lostCreate("New")
            server.set("theirs", "New", "s5")
            // Empty too, but made long before the change.
            server.set("old", "New")
            server.created("old", NOW.minusSeconds(86_400))
            changes.deletePlaylist(Playlist(local, "New"))

            changes.send()

            assertEquals(
                listOf("old", "p1", "theirs"),
                harness.remote.playlists.map { it.id.value }.sorted()
            )
        }

    @Test
    fun `songs the server refuses are left out and the rest applied`() = runBlocking<Unit> {
        server.unknown += "gone"
        changes.renamePlaylist(p1(), "Evening")
        add("s4", "gone", "s5")
        changes.removeFromPlaylist(p1(), 0)

        changes.send()

        assertEquals(listOf("s2", "s3", "s4", "s5"), server.ids("p1"))
        assertEquals("Evening", server.find("p1")!!.name)
        assertEquals(0, waiting())
        val notice = changes.notices.first().single()
        assertEquals("Evening" to 1, notice.playlist to notice.skippedSongs)
    }

    @Test
    fun `a refusal that is not about new songs still drops the change`() = runBlocking<Unit> {
        server.fault = { if (it == "createPlaylist") Fault.REFUSED else null }
        changes.removeFromPlaylist(p1(), 0)

        changes.send()

        assertEquals(0, waiting())
        assertEquals(0, changes.notices.first().single().skippedSongs)
    }

    @Test
    fun `an account the server refuses keeps the whole queue`() = runBlocking<Unit> {
        add("s4")
        changes.setSongFavourite(server.known("s1"), true)
        server.fault = { Fault.REFUSED }
        harness.remote.failing += "me"

        val result = changes.send()

        assertEquals(SendResult(waiting = true), result)
        assertEquals(2, waiting())
        assertTrue(changes.notices.first().isEmpty())
    }

    @Test
    fun `a refusal does not drop what was queued while the request was in flight`() =
        runBlocking<Unit> {
            server.fault = { if (it == "deletePlaylist") Fault.REFUSED else null }
            changes.deletePlaylist(p1())
            var once = true
            server.during = {
                if (it == "deletePlaylist" && once) {
                    once = false
                    runBlocking {
                        changes.renamePlaylist(Playlist(PlaylistId("p1"), "Mix"), "Kept")
                    }
                }
            }

            changes.send()

            assertEquals("Kept", server.find("p1")!!.name)
        }

    @Test
    fun `changes are held while asked to`() = runBlocking<Unit> {
        var hold = true
        val syncer = CatalogSyncer(
            harness.api,
            harness.database,
            harness.config,
            harness.clock,
            holdChanges = { hold }
        )
        val held = DefaultOfflineChanges(syncer, harness.clock)
        held.setSongFavourite(server.known("s1"), true)

        assertEquals(CatalogSyncResult.Synced, syncer.sync())
        assertEquals(SendResult(waiting = true), held.send())
        assertTrue(server.writes.isEmpty())

        hold = false
        syncer.sync()
        assertEquals(setOf("s1"), server.starred)
    }
}
