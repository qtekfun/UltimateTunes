// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.demo

import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesApiFactory
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.AlbumListType
import com.qtekfun.ultimatetunes.core.api.model.ApiKeySecret
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import kotlinx.coroutines.test.runTest
import mockwebserver3.MockWebServer
import okhttp3.Request
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertArrayEquals
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test

/** The demo server answers every screen's call through the real client. */
class DemoDispatcherTest {
    private val key = "utk_" + "d".repeat(43)
    private val clock = Clock.fixed(Instant.parse("2026-10-01T12:00:00Z"), ZoneOffset.UTC)
    private val server = MockWebServer()
    private lateinit var source: InMemoryServerConfigSource
    private lateinit var api: TunesApi

    @BeforeEach
    fun setUp() {
        server.dispatcher = DemoDispatcher(key, clock) { label, _ -> label.encodeToByteArray() }
        server.start()
        source = InMemoryServerConfigSource(ServerConfig(server.url("/"), ApiKeySecret(key)))
        api = TunesApiFactory.create(TunesApiFactory.httpClient(source), source, clock)
    }

    @AfterEach
    fun tearDown() {
        server.close()
    }

    private fun <T> TunesResult<T>.value(): T {
        assertTrue(this is TunesResult.Success, toString())
        return (this as TunesResult.Success).value
    }

    @Test
    fun `connecting checks the server and the key`() = runTest {
        assertEquals("UltimateTunes Demo", api.serverInfo(server.url("/")).value().name)
        assertEquals("demo", api.me().value().username)

        source.set(ServerConfig(server.url("/"), ApiKeySecret("utk_" + "x".repeat(43))))
        assertTrue(api.me() is TunesResult.Unauthorized)
        assertTrue(api.ping() is TunesResult.Unauthorized)
    }

    @Test
    fun `listen now and radio are full`() = runTest {
        val listenNow = api.listenNow().value()
        assertTrue(listenNow.recentlyPlayed.size >= 5)
        assertTrue(listenNow.mostPlayed.size >= 5)
        assertEquals(4, listenNow.favouriteRadios.size)

        val seed = listenNow.favouriteRadios.first().seedId
        val radio = api.radio(seed, 10).value()
        assertEquals(seed, radio.seed.id)
        assertEquals(10, radio.items.size)
        assertEquals(10, api.similarSongs(seed, 10).value().size)
    }

    @Test
    fun `the library browses down to lyrics`() = runTest {
        val artists = api.artists().value().index.flatMap { it.artist }
        assertEquals(DemoCatalog.artists.size, artists.size)
        val artist = api.artist(artists.first().id).value()
        val album = api.album(artist.album.first().id).value()
        assertTrue(album.song.isNotEmpty())
        val song = api.song(album.song.first().id).value()
        assertEquals(album.name, song.album)
        assertTrue(api.lyrics(song.id).value().single().line.isNotEmpty())
        assertEquals(5, api.albumList(AlbumListType.NEWEST, size = 5).value().size)
        assertEquals(3, api.randomSongs(3).value().size)
    }

    @Test
    fun `search finds library and external songs`() = runTest {
        val result = api.search("neon").value()
        assertTrue(result.albums.any { it.name == "Neon Tide" })
        assertTrue(result.tracks.any { it.isExternal })
    }

    @Test
    fun `playlists, favourites and the queue are kept in memory`() = runTest {
        val before = api.playlists().value().size
        val first = DemoCatalog.songs.first().id
        val created = api.createPlaylist("Mine", listOf(first)).value()
        assertEquals(before + 1, api.playlists().value().size)
        api.updatePlaylist(created.id, songIdsToAdd = listOf(first)).value()
        assertEquals(2, api.playlist(created.id).value().entry.size)
        api.deletePlaylist(created.id).value()
        assertEquals(before, api.playlists().value().size)

        api.star(songIds = listOf(first)).value()
        assertTrue(api.starred().value().song.any { it.id == first })
        api.unstar(songIds = listOf(first)).value()
        assertTrue(api.starred().value().song.none { it.id == first })

        api.savePlayQueue(listOf(first), first, 1_000).value()
        assertEquals(first, api.playQueue().value()?.current)
        api.scrobble(first).value()
        api.requestTrack(first).value()
    }

    @Test
    fun `covers and audio are served`() = runTest {
        val album = DemoCatalog.albums.first()
        val client = TunesApiFactory.httpClient(source)
        val cover = checkNotNull(api.coverArtUrl(checkNotNull(album.coverArt), 300))
        client.newCall(Request.Builder().url(cover).build()).execute().use {
            assertEquals("image/png", it.header("Content-Type"))
            assertArrayEquals(album.name.encodeToByteArray(), it.body.bytes())
        }
        val stream = checkNotNull(api.streamUrl(album.song.first().id))
        client.newCall(Request.Builder().url(stream).build()).execute().use {
            assertEquals("RIFF", it.body.bytes().copyOfRange(0, 4).decodeToString())
        }
    }

    @Test
    fun `initials skip small words`() {
        assertEquals("LR", DemoArtwork.initials("Lanterns in the Rye"))
        assertEquals("MO", DemoArtwork.initials("The Midnight Orchard"))
        assertEquals("UT", DemoArtwork.initials("123"))
    }
}
