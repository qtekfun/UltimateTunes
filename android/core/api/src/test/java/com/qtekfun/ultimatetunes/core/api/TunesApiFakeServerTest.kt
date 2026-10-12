// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api

import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.AlbumListType
import com.qtekfun.ultimatetunes.core.api.model.ApiKeyId
import com.qtekfun.ultimatetunes.core.api.model.ArtistId
import com.qtekfun.ultimatetunes.core.api.model.CoverArtId
import com.qtekfun.ultimatetunes.core.api.model.ImportId
import com.qtekfun.ultimatetunes.core.api.model.ImportItemState
import com.qtekfun.ultimatetunes.core.api.model.ImportState
import com.qtekfun.ultimatetunes.core.api.model.LibraryState
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.api.model.RequestReason
import com.qtekfun.ultimatetunes.core.api.model.Role
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.api.model.TrackState
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import kotlinx.coroutines.test.runTest
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Nested
import org.junit.jupiter.api.Test

/**
 * Every [TunesApi] call against the contract-backed fake server: the request it sends and the
 * example it decodes.
 */
class TunesApiFakeServerTest {
    private val clock = Clock.fixed(Instant.parse("2026-10-12T08:00:00Z"), ZoneOffset.UTC)
    private lateinit var server: FakeTunesServer
    private lateinit var api: TunesApi

    @BeforeEach
    fun setUp() {
        server = FakeTunesServer().start()
        api = server.createApi(clock)
    }

    @AfterEach
    fun tearDown() {
        server.close()
    }

    private fun <T> TunesResult<T>.value(): T {
        assertTrue(this is TunesResult.Success, "Expected success, got $this")
        return (this as TunesResult.Success).value
    }

    @Nested
    inner class UtV1 {
        @Test
        fun `serverInfo needs no key and reads the capabilities`() = runTest {
            val info = api.serverInfo(server.baseUrl).value()
            assertEquals("UltimateTunes", info.name)
            assertEquals("1", info.apiVersion)
            assertTrue(info.capabilities.externalSearch)
            assertFalse(info.capabilities.spotifyImport)
            assertEquals(
                listOf("apiKeyAuthentication", "formPost", "songLyrics"),
                info.openSubsonic.extensions
            )
            val request = server.takeRequest()
            assertEquals("/ut/v1/server", request.url.encodedPath)
            assertNull(request.headers["X-Api-Key"])
        }

        @Test
        fun `createKey posts the credentials without a key and returns the secret`() = runTest {
            val created = api.createKey(
                server.baseUrl,
                FakeTunesServer.USERNAME,
                FakeTunesServer.PASSWORD,
                "Pixel 9"
            ).value()
            assertEquals(FakeTunesServer.API_KEY, created.secret.value)
            assertEquals("Pixel 9", created.key.name)
            val request = server.takeRequest()
            assertEquals("POST", request.method)
            assertNull(request.headers["X-Api-Key"])
            val body = request.body!!.utf8()
            assertTrue(body.contains("\"name\":\"Pixel 9\""), body)
            assertTrue(body.contains("\"username\":\"alice\""), body)
        }

        @Test
        fun `createKey with a wrong password is unauthorized`() = runTest {
            val result = api.createKey(server.baseUrl, "alice", "wrong", "Pixel 9")
            assertTrue(result is TunesResult.Unauthorized)
            assertEquals(
                ErrorKind.AUTHENTICATION_FAILED,
                (result as TunesResult.Unauthorized).error.kind
            )
        }

        @Test
        fun `me sends the key as a header, never in the URL`() = runTest {
            val me = api.me().value()
            assertEquals("alice", me.username)
            assertEquals(Role.ADMIN, me.role)
            val request = server.takeRequest()
            assertEquals(FakeTunesServer.API_KEY, request.headers["X-Api-Key"])
            assertNull(request.url.queryParameter("apiKey"))
        }

        @Test
        fun `listKeys and revokeKey`() = runTest {
            val keys = api.listKeys().value().keys
            assertEquals(2, keys.size)
            assertTrue(keys[0].current)
            assertNull(keys[0].revokedAt)
            assertEquals(Instant.parse("2026-10-01T17:21:40Z"), keys[1].revokedAt)
            server.takeRequest()

            assertEquals(
                Unit,
                api.revokeKey(ApiKeyId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01f002")).value()
            )
            val request = server.takeRequest()
            assertEquals("DELETE", request.method)
            assertEquals(
                "/ut/v1/keys/0199d6a2-4c1e-7b3a-9f10-2a6c8e01f002",
                request.url.encodedPath
            )
        }

        @Test
        fun `requestTrack of a yt id is queued, of a library id ready`() = runTest {
            val queued = api.requestTrack(SongId("yt:Qx7Lm2pZ0aB"), RequestReason.PREFETCH).value()
            assertEquals(TrackState.QUEUED, queued.state)
            assertEquals(SongId("yt:Qx7Lm2pZ0aB"), queued.id)
            val request = server.takeRequest()
            assertEquals(
                listOf("ut", "v1", "tracks", "yt:Qx7Lm2pZ0aB", "request"),
                request.url.pathSegments
            )
            assertEquals("{\"reason\":\"prefetch\"}", request.body!!.utf8())

            val ready = api.requestTrack(SongId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01c005")).value()
            assertEquals(TrackState.READY, ready.state)
            assertEquals("{\"reason\":\"keep\"}", server.takeRequest().body!!.utf8())
        }

        @Test
        fun `requestTrack of a malformed yt id is an invalid id`() = runTest {
            val result = api.requestTrack(SongId("yt:abc"))
            assertTrue(result is TunesResult.ApiError, "$result")
            assertEquals(ErrorKind.INVALID_ID, (result as TunesResult.ApiError).error.kind)
            assertEquals(400, result.httpStatus)
        }

        @Test
        fun `trackStatus follows the selected example`() = runTest {
            val id = SongId("yt:Qx7Lm2pZ0aB")
            server.dispatcher.trackStatusExample = "downloading"
            val downloading = api.trackStatus(id).value()
            assertEquals(TrackState.DOWNLOADING, downloading.state)
            assertTrue(downloading.state.isInProgress)
            assertEquals(0.42, downloading.progress)

            server.dispatcher.trackStatusExample = "ready"
            val ready = api.trackStatus(id).value()
            assertEquals(SongId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01c005"), ready.trackId)
            assertFalse(ready.state.isInProgress)

            server.dispatcher.trackStatusExample = "failed"
            val failed = api.trackStatus(id).value()
            assertEquals(TrackState.FAILED, failed.state)
            assertEquals("video_unavailable", failed.error?.code)

            server.dispatcher.trackStatusExample = "notRequested"
            val notRequested = api.trackStatus(id).value()
            assertEquals(TrackState.NOT_REQUESTED, notRequested.state)
            assertNull(notRequested.trackId)
            assertNull(notRequested.updatedAt)
        }

        @Test
        fun `radio mixes library and external items`() = runTest {
            val radio = api.radio(
                SongId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01c001"),
                limit = 25
            ).value()
            assertEquals("Lighthouse Keeper", radio.seed.title)
            val external = radio.items.first { it.isExternal }
            assertTrue(external.id.isExternal)
            assertTrue(external.albumId!!.isExternal)
            assertTrue(external.artistId!!.isExternal)
            assertNull(external.year)
            assertEquals(
                LibraryState.PENDING,
                radio.items.first {
                    it.libraryState ==
                        LibraryState.PENDING
                }.libraryState
            )
            val request = server.takeRequest()
            assertEquals("0199d6a2-4c1e-7b3a-9f10-2a6c8e01c001", request.url.queryParameter("seed"))
            assertEquals("25", request.url.queryParameter("limit"))
        }

        @Test
        fun `search sends the query and decodes every kind`() = runTest {
            val result = api.search("lanterns", limit = 5, external = false).value()
            assertEquals("lanterns", result.query)
            assertEquals(2, result.artists.size)
            assertEquals(ArtistId("ytartist:UCh5Kp2Wq7Zt3Lm9Xv1Nb4Rs"), result.artists[1].id)
            assertEquals(AlbumId("ytalbum:MPREb_k3Vd9QmT2xL"), result.albums[1].id)
            assertEquals(3, result.tracks.size)
            val request = server.takeRequest()
            assertEquals("lanterns", request.url.queryParameter("q"))
            assertEquals("5", request.url.queryParameter("limit"))
            assertEquals("false", request.url.queryParameter("external"))

            api.search("lanterns").value()
            val defaults = server.takeRequest()
            assertNull(defaults.url.queryParameter("external"))
            assertNull(defaults.url.queryParameter("limit"))
        }

        @Test
        fun `listenNow has every shelf`() = runTest {
            val shelves = api.listenNow().value()
            assertEquals(2, shelves.recentlyPlayed.size)
            assertEquals(3, shelves.recentlyAdded.size)
            assertEquals(3, shelves.mostPlayed.size)
            assertEquals(
                SongId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01c001"),
                shelves.favouriteRadios.single().seedId
            )
        }

        @Test
        fun `imports list, create and progress`() = runTest {
            val list = api.imports(limit = 10, offset = 20).value()
            assertEquals(ImportState.DONE, list.single().state)
            assertTrue(list.single().items.isEmpty())
            val listRequest = server.takeRequest()
            assertEquals("10", listRequest.url.queryParameter("limit"))
            assertEquals("20", listRequest.url.queryParameter("offset"))

            val created = api.createImport(
                "https://music.youtube.com/playlist?list=PLx9",
                "Road Trip 2026"
            ).value()
            assertEquals(ImportState.QUEUED, created.state)
            assertNull(created.playlistId)
            val body = server.takeRequest().body!!.utf8()
            assertEquals(
                "{\"url\":\"https://music.youtube.com/playlist?list=PLx9\",\"name\":\"Road Trip 2026\"}",
                body
            )

            api.createImport("https://music.youtube.com/playlist?list=PLx9").value()
            assertEquals(
                "{\"url\":\"https://music.youtube.com/playlist?list=PLx9\"}",
                server.takeRequest().body!!.utf8()
            )

            val done = api.import(ImportId("0199d6a2-4c1e-7b3a-9f10-2a6c8e017001")).value()
            assertEquals(3, done.items.size)
            assertEquals(ImportItemState.NOT_FOUND, done.items[2].state)
            assertNull(done.items[2].track)
            assertEquals(PlaylistId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01e001"), done.playlistId)

            server.dispatcher.importExample = "queued"
            assertEquals(
                ImportState.QUEUED,
                api.import(ImportId("0199d6a2-4c1e-7b3a-9f10-2a6c8e017001")).value().state
            )
        }
    }

    @Nested
    inner class OpenSubsonic {
        @Test
        fun `ping sends apiKey, v, c and f=json as parameters`() = runTest {
            assertEquals(Unit, api.ping().value())
            val url = server.takeRequest().url
            assertEquals("/rest/ping", url.encodedPath)
            assertEquals(FakeTunesServer.API_KEY, url.queryParameter("apiKey"))
            assertEquals("1.16.1", url.queryParameter("v"))
            assertEquals("UltimateTunes-Android", url.queryParameter("c"))
            assertEquals("json", url.queryParameter("f"))
            assertNull(url.queryParameter("u"))
        }

        @Test
        fun `artists index`() = runTest {
            val indexes = api.artists().value()
            assertEquals(listOf("M", "N", "P"), indexes.index.map { it.name })
            assertEquals("Vega, Marisol", indexes.index[0].artist.single().sortName)
        }

        @Test
        fun `artist with albums`() = runTest {
            val artist = api.artist(ArtistId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01a001")).value()
            assertEquals("The Paper Lanterns", artist.name)
            assertFalse(artist.isExternal)
            assertEquals("Harbour Lights", artist.album.single().name)
            assertEquals(
                "0199d6a2-4c1e-7b3a-9f10-2a6c8e01a001",
                server.takeRequest().url.queryParameter("id")
            )
        }

        @Test
        fun `album with songs and replay gain`() = runTest {
            val album = api.album(AlbumId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01b001")).value()
            assertEquals(2, album.song.size)
            assertFalse(album.isExternal)
            val first = album.song.first()
            assertEquals(-7.12, first.replayGain?.trackGain)
            assertEquals(Instant.parse("2026-10-02T08:00:00Z"), first.starred)
            assertEquals(CoverArtId("al-0199d6a2-4c1e-7b3a-9f10-2a6c8e01b001"), first.coverArt)
            assertFalse(first.isExternal)
        }

        @Test
        fun `song`() = runTest {
            val song = api.song(SongId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01c001")).value()
            assertEquals("Lighthouse Keeper", song.title)
            assertEquals(214, song.duration)
            assertEquals(3_489_211L, song.size)
        }

        @Test
        fun `albumList sends type and paging`() = runTest {
            val albums = api.albumList(
                AlbumListType.NEWEST,
                size = 5,
                offset = 10,
                fromYear = 2020,
                toYear = 2025,
                genre = "Pop"
            )
                .value()
            assertTrue(albums.isNotEmpty())
            val url = server.takeRequest().url
            assertEquals("newest", url.queryParameter("type"))
            assertEquals("5", url.queryParameter("size"))
            assertEquals("10", url.queryParameter("offset"))
            assertEquals("2020", url.queryParameter("fromYear"))
            assertEquals("2025", url.queryParameter("toYear"))
            assertEquals("Pop", url.queryParameter("genre"))
        }

        @Test
        fun `randomSongs and similarSongs`() = runTest {
            assertTrue(api.randomSongs(size = 3, genre = "Indie Pop").value().isNotEmpty())
            val random = server.takeRequest().url
            assertEquals("3", random.queryParameter("size"))
            assertEquals("Indie Pop", random.queryParameter("genre"))

            val similar = api.similarSongs(
                SongId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01c001"),
                count = 10
            ).value()
            assertTrue(similar.any { it.isExternal })
            assertEquals("10", server.takeRequest().url.queryParameter("count"))
        }

        @Test
        fun `lyrics are synced with millisecond starts`() = runTest {
            val lyrics = api.lyrics(SongId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01c001")).value().single()
            assertTrue(lyrics.synced)
            assertEquals("und", lyrics.lang)
            assertEquals(4210L, lyrics.line[1].startMillis)
        }

        @Test
        fun `playlists, playlist, create, update and delete`() = runTest {
            assertEquals("Sunday Morning", api.playlists().value().single().name)
            server.takeRequest()

            val playlist = api.playlist(PlaylistId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01e001")).value()
            assertTrue(playlist.entry.isNotEmpty())
            server.takeRequest()

            val ids =
                listOf(SongId("yt:Qx7Lm2pZ0aB"), SongId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01c001"))
            assertNotNull(api.createPlaylist("Road", ids).value())
            val create = server.takeRequest().url
            assertEquals("Road", create.queryParameter("name"))
            assertEquals(ids.map { it.value }, create.queryParameterValues("songId"))

            api.updatePlaylist(
                PlaylistId("p1"),
                name = "New",
                comment = "c",
                public = true,
                songIdsToAdd = ids,
                songIndexesToRemove = listOf(0, 2)
            ).value()
            val update = server.takeRequest().url
            assertEquals("p1", update.queryParameter("playlistId"))
            assertEquals("New", update.queryParameter("name"))
            assertEquals("c", update.queryParameter("comment"))
            assertEquals("true", update.queryParameter("public"))
            assertEquals(ids.map { it.value }, update.queryParameterValues("songIdToAdd"))
            assertEquals(listOf("0", "2"), update.queryParameterValues("songIndexToRemove"))

            api.updatePlaylist(PlaylistId("p1")).value()
            assertEquals(
                setOf("playlistId", "apiKey", "v", "c", "f"),
                server.takeRequest().url.queryParameterNames
            )

            api.deletePlaylist(PlaylistId("p1")).value()
            assertEquals("p1", server.takeRequest().url.queryParameter("id"))
        }

        @Test
        fun `star, unstar and starred`() = runTest {
            api.star(
                songIds = listOf(SongId("yt:Qx7Lm2pZ0aB")),
                albumIds = listOf(AlbumId("a1")),
                artistIds = listOf(ArtistId("r1"))
            ).value()
            val star = server.takeRequest().url
            assertEquals("/rest/star", star.encodedPath)
            assertEquals(listOf("yt:Qx7Lm2pZ0aB"), star.queryParameterValues("id"))
            assertEquals(listOf("a1"), star.queryParameterValues("albumId"))
            assertEquals(listOf("r1"), star.queryParameterValues("artistId"))

            api.unstar(songIds = listOf(SongId("s1"))).value()
            val unstar = server.takeRequest().url
            assertEquals("/rest/unstar", unstar.encodedPath)
            assertEquals(listOf("s1"), unstar.queryParameterValues("id"))

            val starred = api.starred().value()
            assertTrue(starred.song.isNotEmpty())
        }

        @Test
        fun `scrobble uses the injected clock unless a time is given`() = runTest {
            api.scrobble(SongId("s1")).value()
            val now = server.takeRequest().url
            assertEquals(clock.millis().toString(), now.queryParameter("time"))
            assertEquals("true", now.queryParameter("submission"))

            api.scrobble(
                SongId("s1"),
                submission = false,
                playedAt = Instant.ofEpochMilli(1234)
            ).value()
            val nowPlaying = server.takeRequest().url
            assertEquals("1234", nowPlaying.queryParameter("time"))
            assertEquals("false", nowPlaying.queryParameter("submission"))
        }

        @Test
        fun `play queue read and save`() = runTest {
            val queue = api.playQueue().value()
            assertNotNull(queue)
            assertEquals(73_500L, queue!!.position)
            assertEquals("UltimateTunes-Android", queue.changedBy)
            server.takeRequest()

            api.savePlayQueue(
                listOf(SongId("a"), SongId("yt:Qx7Lm2pZ0aB")),
                SongId("a"),
                1500
            ).value()
            val save = server.takeRequest().url
            assertEquals(listOf("a", "yt:Qx7Lm2pZ0aB"), save.queryParameterValues("id"))
            assertEquals("a", save.queryParameter("current"))
            assertEquals("1500", save.queryParameter("position"))
        }
    }

    @Nested
    inner class MediaUrls {
        @Test
        fun `stream, download and cover URLs carry no credentials`() {
            val stream = api.streamUrl(SongId("yt:Qx7Lm2pZ0aB"))!!
            assertEquals("/rest/stream", stream.encodedPath)
            assertEquals("yt:Qx7Lm2pZ0aB", stream.queryParameter("id"))
            assertNull(stream.queryParameter("apiKey"))
            assertFalse(stream.toString().contains(FakeTunesServer.API_KEY))

            assertEquals("/rest/download", api.downloadUrl(SongId("s1"))!!.encodedPath)

            val cover = api.coverArtUrl(CoverArtId("al-1"), size = 300)!!
            assertEquals("300", cover.queryParameter("size"))
            assertNull(api.coverArtUrl(CoverArtId("al-1")).let { it!!.queryParameter("size") })
        }

        @Test
        fun `the authenticated client plays the stream URL`() {
            val source = InMemoryServerConfigSource(server.serverConfig())
            val client = TunesApiFactory.httpClient(source)
            val tunes = TunesApiFactory.create(client, source, clock)
            val response = client.newCall(
                okhttp3.Request.Builder().url(tunes.streamUrl(SongId("s1"))!!).build()
            ).execute()
            response.use {
                assertEquals(200, it.code)
                assertEquals("audio/ogg", it.header("Content-Type"))
                assertEquals("bytes", it.header("Accept-Ranges"))
                assertTrue(it.body.bytes().isNotEmpty())
            }
            assertEquals(FakeTunesServer.API_KEY, server.takeRequest().url.queryParameter("apiKey"))

            val growing = client.newCall(
                okhttp3.Request.Builder().url(tunes.streamUrl(SongId("yt:Qx7Lm2pZ0aB"))!!).build()
            )
                .execute()
            growing.use {
                assertEquals("none", it.header("Accept-Ranges"))
                assertNull(it.header("Content-Length"))
            }

            val cover = client.newCall(
                okhttp3.Request.Builder().url(tunes.coverArtUrl(CoverArtId("al-1"))!!).build()
            ).execute()
            cover.use {
                assertEquals("image/png", it.header("Content-Type"))
                assertEquals(0x89.toByte(), it.body.bytes()[0])
            }
        }

        @Test
        fun `no URLs without a server`() {
            val tunes = TunesApiFactory.create(
                TunesApiFactory.httpClient(InMemoryServerConfigSource()),
                InMemoryServerConfigSource(),
                clock
            )
            assertNull(tunes.streamUrl(SongId("s1")))
            assertNull(tunes.downloadUrl(SongId("s1")))
            assertNull(tunes.coverArtUrl(CoverArtId("c")))
        }
    }
}
