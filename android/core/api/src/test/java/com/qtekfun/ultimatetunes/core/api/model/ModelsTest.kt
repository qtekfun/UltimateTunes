// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api.model

import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.internal.TunesJson
import java.time.Instant
import kotlinx.serialization.SerializationException
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class IdsTest {
    @Test
    fun `yt ids are external and keep their exact text through JSON`() {
        val id = SongId("yt:Qx7Lm2pZ0aB")
        assertTrue(id.isExternal)
        assertEquals(IdOrigin.YOUTUBE, id.origin)
        assertEquals("Qx7Lm2pZ0aB", id.videoId)
        assertEquals("\"yt:Qx7Lm2pZ0aB\"", Json.encodeToString(SongId.serializer(), id))
        assertEquals(id, Json.decodeFromString(SongId.serializer(), "\"yt:Qx7Lm2pZ0aB\""))
        assertEquals("yt:Qx7Lm2pZ0aB", id.toString())
    }

    @Test
    fun `library ids are opaque UUIDs`() {
        val id = SongId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01c001")
        assertFalse(id.isExternal)
        assertEquals(IdOrigin.LIBRARY, id.origin)
        assertNull(id.videoId)
        // A prefix check only: an id merely containing "yt:" is still a library id.
        assertFalse(SongId("xyt:Qx7Lm2pZ0aB").isExternal)
        assertFalse(SongId("YT:Qx7Lm2pZ0aB").isExternal)
    }

    @Test
    fun `ofVideo builds a yt id from a valid video id only`() {
        assertEquals(SongId("yt:Qx7Lm2pZ0aB"), SongId.ofVideo("Qx7Lm2pZ0aB"))
        assertEquals(SongId("yt:a-b_c-d_e-f"), SongId.ofVideo("a-b_c-d_e-f"))
        listOf("abc", "Qx7Lm2pZ0aB1", "Qx7Lm2pZ0a!", "../../etc/p", " Qx7Lm2pZ0aB").forEach {
            assertThrows(IllegalArgumentException::class.java, { SongId.ofVideo(it) }, it)
        }
    }

    @Test
    fun `album and artist ids tell YouTube Music items apart`() {
        assertTrue(AlbumId("ytalbum:MPREb_k3Vd9QmT2xL").isExternal)
        assertEquals(IdOrigin.YOUTUBE, AlbumId("ytalbum:MPREb_k3Vd9QmT2xL").origin)
        assertFalse(AlbumId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01b001").isExternal)
        assertEquals(IdOrigin.LIBRARY, AlbumId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01b001").origin)
        assertTrue(ArtistId("ytartist:UCq8XbV1r0LwZ5mN3tYp7kQe").isExternal)
        assertEquals(IdOrigin.YOUTUBE, ArtistId("ytartist:UCq8XbV1r0LwZ5mN3tYp7kQe").origin)
        assertEquals(IdOrigin.LIBRARY, ArtistId("0199d6a2-4c1e-7b3a-9f10-2a6c8e01a001").origin)
        // A song's yt: prefix is not an album's.
        assertFalse(AlbumId("yt:Qx7Lm2pZ0aB").isExternal)
        assertEquals("ytalbum:x", AlbumId("ytalbum:x").toString())
        assertEquals("ytartist:x", ArtistId("ytartist:x").toString())
    }

    @Test
    fun `the other ids print their value`() {
        assertEquals("al-1", CoverArtId("al-1").toString())
        assertEquals("p", PlaylistId("p").toString())
        assertEquals("k", ApiKeyId("k").toString())
        assertEquals("i", ImportId("i").toString())
        assertEquals("u", UserId("u").toString())
    }

    @Test
    fun `external songs, albums and artists from the API`() {
        val song = Song(id = SongId("yt:Qx7Lm2pZ0aB"), title = "t")
        assertTrue(song.isExternal)
        assertTrue(Album(id = AlbumId("ytalbum:x"), name = "a").isExternal)
        assertTrue(Artist(id = ArtistId("ytartist:x"), name = "a").isExternal)
    }
}

class SecretsTest {
    private val key = "utk_EXAMPLEexampleEXAMPLEexampleEXAMPLEexampleE"

    @Test
    fun `the key never shows in strings`() {
        val secret = ApiKeySecret(key)
        assertFalse(secret.toString().contains(key))
        assertFalse("$secret".contains("EXAMPLEexample"))
        assertEquals("utk_EXAMPLEe", secret.prefix)
        val config = ServerConfig("https://music.example.net".toHttpUrl(), secret)
        assertFalse(config.toString().contains(key))
        val created = CreatedKey(
            ApiKey(ApiKeyId("k"), "Pixel 9", "utk_EXAMPLEe", Instant.EPOCH),
            secret
        )
        assertFalse(created.toString().contains(key))
    }

    @Test
    fun `the password never shows in the key request`() {
        val request = CreateKeyRequest("alice", "correct horse battery staple", "Pixel 9")
        assertFalse(request.toString().contains("correct horse"))
        assertTrue(request.toString().contains("alice"))
        val withCode = CreateKeyRequest("alice", "pw", "Pixel 9", "123456")
        assertFalse(withCode.toString().contains("123456"))
    }

    @Test
    fun `key format`() {
        assertTrue(ApiKeySecret.isWellFormed(key))
        assertFalse(ApiKeySecret.isWellFormed("utk_short"))
        assertFalse(ApiKeySecret.isWellFormed("xyz_EXAMPLEexampleEXAMPLEexampleEXAMPLEexampleE"))
        assertFalse(ApiKeySecret.isWellFormed("$key "))
    }
}

class ServerConfigTest {
    private val secret = ApiKeySecret("utk_" + "k".repeat(43))

    @Test
    fun `the root always ends with a slash and drops query and fragment`() {
        assertEquals(
            "https://music.example.net/",
            ServerConfig("https://music.example.net".toHttpUrl(), secret).root.toString()
        )
        assertEquals(
            "https://example.net/music/",
            ServerConfig("https://example.net/music?x=1#y".toHttpUrl(), secret).root.toString()
        )
        assertEquals(
            "https://example.net/music/",
            ServerConfig("https://example.net/music/".toHttpUrl(), secret).root.toString()
        )
    }
}

class SerializationTest {
    @Test
    fun `timestamps accept Z and explicit offsets, and reject garbage`() {
        val serializer = InstantSerializer
        assertEquals(
            Instant.parse("2026-10-12T08:15:30.123Z"),
            TunesJson.decodeFromString(serializer, "\"2026-10-12T08:15:30.123Z\"")
        )
        assertEquals(
            Instant.parse("2026-10-12T06:15:30Z"),
            TunesJson.decodeFromString(serializer, "\"2026-10-12T08:15:30+02:00\"")
        )
        assertEquals(
            "\"2026-10-12T08:15:30Z\"",
            TunesJson.encodeToString(serializer, Instant.parse("2026-10-12T08:15:30Z"))
        )
        assertThrows(SerializationException::class.java) {
            TunesJson.decodeFromString(serializer, "\"yesterday\"")
        }
    }

    @Test
    fun `enums use the wire names`() {
        assertEquals(
            "\"not_requested\"",
            TunesJson.encodeToString(TrackState.serializer(), TrackState.NOT_REQUESTED)
        )
        assertEquals(
            TrackState.TAGGING,
            TunesJson.decodeFromString(TrackState.serializer(), "\"tagging\"")
        )
        assertTrue(TrackState.TAGGING.isInProgress)
        assertTrue(TrackState.QUEUED.isInProgress)
        assertFalse(TrackState.CANCELLED.isInProgress)
        assertEquals(
            ImportSource.EXPORTIFY_CSV,
            TunesJson.decodeFromString(ImportSource.serializer(), "\"exportify_csv\"")
        )
        assertEquals(
            listOf("csv", "exportify_csv", "spotify_json"),
            ImportFileFormat.entries.map { it.wireName }
        )
        assertEquals(Role.USER, TunesJson.decodeFromString(Role.serializer(), "\"user\""))
        assertEquals(
            LibraryState.FAILED,
            TunesJson.decodeFromString(LibraryState.serializer(), "\"failed\"")
        )
        assertEquals(
            listOf(
                "random", "newest", "highest", "frequent", "recent", "alphabeticalByName",
                "alphabeticalByArtist", "starred", "byYear", "byGenre"
            ),
            AlbumListType.entries.map { it.wireName }
        )
    }

    @Test
    fun `unknown properties are ignored and unsynced lines have no start`() {
        val line = TunesJson.decodeFromString(
            LyricLine.serializer(),
            "{\"value\":\"la\",\"future\":1}"
        )
        assertNull(line.startMillis)
        assertEquals("la", line.value)
        assertEquals(1500L, LyricLine("x", 1500.7).startMillis)
        assertEquals("\"x\"", TunesJson.encodeToString(String.serializer(), "x"))
    }
}
