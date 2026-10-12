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
import com.qtekfun.ultimatetunes.core.api.model.ImportFileFormat
import com.qtekfun.ultimatetunes.core.api.model.ImportSource
import com.qtekfun.ultimatetunes.core.api.model.ImportState
import java.time.Clock
import java.time.Instant
import java.time.ZoneId
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
    private val clock = object : Clock() {
        var now: Instant = Instant.parse("2026-10-01T12:00:00Z")

        override fun instant(): Instant = now

        override fun getZone(): ZoneId = ZoneOffset.UTC

        override fun withZone(zone: ZoneId?): Clock = this
    }
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
    fun `an import progresses and ends in a playlist`() = runTest {
        val history = api.imports().value()
        assertEquals(1, history.size)
        assertEquals(ImportState.DONE, history.single().state)
        val playlistsBefore = api.playlists().value().size

        val created = api.createImport("https://music.youtube.com/playlist?list=x", "Mine").value()
        assertEquals(ImportState.QUEUED, created.state)

        clock.now = clock.now.plusSeconds(6)
        val halfway = api.import(created.id).value()
        assertEquals(ImportState.MATCHING, halfway.state)
        assertTrue(halfway.progress > 0.0 && halfway.progress < 1.0, halfway.toString())

        clock.now = clock.now.plusSeconds(10)
        val done = api.import(created.id).value()
        assertEquals(ImportState.DONE, done.state)
        assertEquals(done.total, done.matched + done.notFound)
        assertTrue(done.notFound > 0)
        val playlist = api.playlist(checkNotNull(done.playlistId)).value()
        assertEquals("Mine", playlist.name)
        assertEquals(done.matched, playlist.entry.size)
        assertEquals(playlistsBefore + 1, api.playlists().value().size)
        assertEquals(2, api.imports().value().size)
    }

    @Test
    fun `a file import is accepted`() = runTest {
        val created = api.createFileImport(
            "title,artist\nA,B\n".encodeToByteArray(),
            "list.csv",
            ImportFileFormat.CSV,
            "From a file"
        ).value()
        assertEquals(ImportSource.CSV, created.source)
        assertEquals("From a file", created.name)
        assertTrue(api.createImport("not a url") is TunesResult.ApiError)
    }

    @Test
    fun `a playlist song can be removed and the playlist renamed`() = runTest {
        val playlist = api.playlists().value().first()
        val before = api.playlist(playlist.id).value().entry
        api.updatePlaylist(playlist.id, name = "Renamed", songIndexesToRemove = listOf(0)).value()
        val after = api.playlist(playlist.id).value()
        assertEquals("Renamed", after.name)
        assertEquals(before.drop(1), after.entry)
    }

    @Test
    fun `keys can be listed and revoked`() = runTest {
        assertTrue(api.listKeys().value().keys.single().current)
        api.revokeKey(api.listKeys().value().keys.single().id).value()
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
