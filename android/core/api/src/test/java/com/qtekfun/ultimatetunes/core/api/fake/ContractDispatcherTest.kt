// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api.fake

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.FormBody
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.junit.jupiter.params.ParameterizedTest
import org.junit.jupiter.params.provider.ValueSource

/** The fake server itself: the contracts' auth rules, and every endpoint the app uses answers. */
class ContractDispatcherTest {
    private val client = OkHttpClient()
    private lateinit var server: FakeTunesServer
    private val key = FakeTunesServer.API_KEY

    @BeforeEach
    fun setUp() {
        server = FakeTunesServer().start()
    }

    @AfterEach
    fun tearDown() {
        server.close()
    }

    private fun get(pathAndQuery: String, header: String? = null): Pair<Int, String> {
        val request = Request.Builder().url(server.baseUrl.resolve(pathAndQuery)!!)
            .apply { if (header != null) header("X-Api-Key", header) }
            .build()
        return client.newCall(request).execute().use { it.code to it.body.string() }
    }

    private fun subsonicCode(body: String): Int? =
        Json.parseToJsonElement(body).jsonObject.getValue("subsonic-response").jsonObject["error"]
            ?.jsonObject?.getValue("code")?.jsonPrimitive?.int

    private fun problemCode(body: String): String =
        Json.parseToJsonElement(body).jsonObject.getValue("code").jsonPrimitive.content

    @ParameterizedTest
    @ValueSource(
        strings = [
            "ping", "getLicense", "getOpenSubsonicExtensions", "tokenInfo", "getMusicFolders",
            "getArtists", "getArtist", "getAlbum", "getSong", "getAlbumList2", "getRandomSongs",
            "search3", "getLyricsBySongId", "getPlaylists", "getPlaylist", "createPlaylist",
            "updatePlaylist", "deletePlaylist", "star", "unstar", "getStarred2", "scrobble",
            "getSimilarSongs2", "getPlayQueue", "savePlayQueue"
        ]
    )
    fun `every OpenSubsonic endpoint answers ok with its example`(endpoint: String) {
        val (code, body) = get("/rest/$endpoint?apiKey=$key&f=json&id=x")
        assertEquals(200, code)
        assertEquals(null, subsonicCode(body), body)
        assertEquals(
            Json.parseToJsonElement(ContractFixtures.openSubsonic("${endpoint}_ok")),
            Json.parseToJsonElement(body)
        )
    }

    @Test
    fun `the legacy view suffix and form POST work too`() {
        assertEquals(null, subsonicCode(get("/rest/ping.view?apiKey=$key").second))
        val form = FormBody.Builder().add("apiKey", key).add("id", "a").add("id", "b").build()
        val request = Request.Builder().url(
            server.baseUrl.resolve("/rest/star")!!
        ).post(form).build()
        val body = client.newCall(request).execute().use { it.body.string() }
        assertEquals(null, subsonicCode(body))
    }

    @Test
    fun `OpenSubsonic auth rules`() {
        assertEquals(10, subsonicCode(get("/rest/ping").second))
        assertEquals(44, subsonicCode(get("/rest/ping?apiKey=nope").second))
        assertEquals(43, subsonicCode(get("/rest/ping?apiKey=$key&u=alice").second))
        assertEquals(42, subsonicCode(get("/rest/ping?u=alice&t=abc&s=salt").second))
        assertEquals(40, subsonicCode(get("/rest/ping?u=alice&p=wrong").second))
        assertEquals(null, subsonicCode(get("/rest/ping?u=alice&p=$key").second))
        val hex = key.encodeToByteArray().joinToString("") { "%02x".format(it) }
        assertEquals(null, subsonicCode(get("/rest/ping?u=alice&p=enc:$hex").second))
        assertEquals(null, subsonicCode(get("/rest/getOpenSubsonicExtensions").second))
    }

    @Test
    fun `missing ids and unknown endpoints`() {
        assertEquals(10, subsonicCode(get("/rest/getAlbum?apiKey=$key").second))
        val (code, body) = get("/rest/getIndexes?apiKey=$key")
        assertEquals(501, code)
        assertEquals(0, subsonicCode(body))
        assertEquals(404, get("/elsewhere").first)
    }

    @Test
    fun `ut-v1 auth rules`() {
        assertEquals(200, get("/ut/v1/server").first)
        assertEquals("authentication_required", problemCode(get("/ut/v1/me").second))
        assertEquals("invalid_api_key", problemCode(get("/ut/v1/me", header = "nope").second))
        assertEquals(200, get("/ut/v1/me?apiKey=$key").first)
        val (code, body) = get("/ut/v1/me?apiKey=other", header = key)
        assertEquals(400, code)
        assertEquals("conflicting_auth", problemCode(body))
        assertEquals(200, get("/ut/v1/me?apiKey=$key", header = key).first)
    }

    @Test
    fun `ut-v1 validation and unknown paths`() {
        assertEquals("missing_parameter", problemCode(get("/ut/v1/search", header = key).second))
        assertEquals("missing_parameter", problemCode(get("/ut/v1/radio", header = key).second))
        assertEquals(
            "invalid_id",
            problemCode(get("/ut/v1/radio?seed=yt:bad", header = key).second)
        )
        assertEquals(
            "invalid_id",
            problemCode(get("/ut/v1/tracks/yt:bad/status", header = key).second)
        )
        val (code, body) = get("/ut/v1/nothing", header = key)
        assertEquals(404, code)
        assertEquals("not_found", problemCode(body))
    }

    @Test
    fun `createKey checks the body and creating an import gives its Location`() {
        val json = "application/json".toMediaType()
        val bad = Request.Builder().url(
            server.baseUrl.resolve("/ut/v1/keys")!!
        ).post("{}".toRequestBody(json)).build()
        client.newCall(bad).execute().use { assertEquals(401, it.code) }

        val created = Request.Builder().url(server.baseUrl.resolve("/ut/v1/imports")!!)
            .header("X-Api-Key", key)
            .post("{\"url\":\"https://music.youtube.com/playlist?list=x\"}".toRequestBody(json))
            .build()
        client.newCall(created).execute().use {
            assertEquals(202, it.code)
            assertTrue(it.header("Location")!!.startsWith("/ut/v1/imports/"))
        }
    }

    @Test
    fun `file imports need a file and a known format`() {
        fun upload(vararg parts: Pair<String, String>): Pair<Int, String> {
            val body = MultipartBody.Builder().setType(MultipartBody.FORM).apply {
                parts.forEach { (name, value) ->
                    if (name ==
                        "file"
                    ) {
                        addFormDataPart(name, "p.csv", value.toRequestBody())
                    } else {
                        addFormDataPart(name, value)
                    }
                }
            }.build()
            val request = Request.Builder().url(server.baseUrl.resolve("/ut/v1/imports")!!)
                .header("X-Api-Key", key).post(body).build()
            return client.newCall(request).execute().use { it.code to it.body.string() }
        }
        assertEquals(202, upload("file" to "title,artist\n", "format" to "exportify_csv").first)
        assertEquals("missing_parameter", problemCode(upload("format" to "csv").second))
        assertEquals("missing_parameter", problemCode(upload("file" to "x").second))
        assertEquals(
            "invalid_parameter",
            problemCode(upload("file" to "x", "format" to "xlsx").second)
        )

        val json = "application/json".toMediaType()
        val noUrl = Request.Builder().url(server.baseUrl.resolve("/ut/v1/imports")!!)
            .header("X-Api-Key", key).post("{}".toRequestBody(json)).build()
        client.newCall(noUrl).execute().use {
            assertEquals("missing_parameter", problemCode(it.body.string()))
        }
    }

    @Test
    fun `overrides replace an endpoint until cleared`() {
        server.dispatcher.override("/rest/ping") { mockwebserver3.MockResponse(code = 503) }
        assertEquals(503, get("/rest/ping?apiKey=$key").first)
        server.dispatcher.clearOverrides()
        assertEquals(200, get("/rest/ping?apiKey=$key").first)
    }
}
