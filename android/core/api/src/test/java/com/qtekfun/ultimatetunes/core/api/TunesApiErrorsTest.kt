// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api

import com.qtekfun.ultimatetunes.core.api.fake.ContractFixtures
import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.SongId
import java.time.Clock
import java.time.Duration
import java.time.Instant
import java.time.ZoneOffset
import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import okhttp3.Headers.Companion.headersOf
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test

/** How [TunesApi] turns every kind of failure into a [TunesResult.Failure]. */
class TunesApiErrorsTest {
    private val clock = Clock.fixed(Instant.parse("2026-10-12T08:00:00Z"), ZoneOffset.UTC)
    private lateinit var server: FakeTunesServer

    @BeforeEach
    fun setUp() {
        server = FakeTunesServer().start()
    }

    @AfterEach
    fun tearDown() {
        server.close()
    }

    private fun json(code: Int, body: String, vararg headers: String) = MockResponse(
        code = code,
        headers = headersOf("Content-Type", "application/json", *headers),
        body = body
    )

    @Test
    fun `an unknown key is unauthorized on both APIs`() = runTest {
        val api = server.createApi(clock, apiKey = "utk_" + "x".repeat(43))
        val rest = api.ping()
        assertTrue(rest is TunesResult.Unauthorized, "$rest")
        rest as TunesResult.Unauthorized
        assertEquals(ErrorKind.INVALID_API_KEY, rest.error.kind)
        assertEquals("44", rest.error.code)
        assertEquals("https://music.example.net/ut/docs/api-keys", rest.error.helpUrl)
        assertEquals(200, rest.httpStatus)

        val ut = api.me()
        assertTrue(ut is TunesResult.Unauthorized, "$ut")
        ut as TunesResult.Unauthorized
        assertEquals(ErrorKind.INVALID_API_KEY, ut.error.kind)
        assertEquals(401, ut.httpStatus)
        assertEquals("The API key is unknown or revoked", ut.error.message)
    }

    @Test
    fun `a not found envelope is an api error`() = runTest {
        server.dispatcher.override("rest/getAlbum") {
            json(200, ContractFixtures.openSubsonic("failed_notFound"))
        }
        val result = server.createApi(clock).album(AlbumId("missing"))
        assertTrue(result is TunesResult.ApiError, "$result")
        result as TunesResult.ApiError
        assertEquals(ErrorKind.NOT_FOUND, result.error.kind)
        assertEquals("Song not found", result.error.message)
    }

    @Test
    fun `rate limiting on rest carries Retry-After`() = runTest {
        server.dispatcher.override("rest/ping") {
            json(429, ContractFixtures.openSubsonic("response.RateLimited"), "Retry-After", "60")
        }
        val result = server.createApi(clock).ping() as TunesResult.ApiError
        assertEquals(ErrorKind.RATE_LIMITED, result.error.kind)
        assertEquals(Duration.ofSeconds(60), result.error.retryAfter)
        assertEquals(429, result.httpStatus)
    }

    @Test
    fun `router stubs on rest are not implemented`() = runTest {
        server.dispatcher.override("rest/getStarred2") {
            json(501, ContractFixtures.openSubsonic("response.NotImplemented"))
        }
        val result = server.createApi(clock).starred() as TunesResult.ApiError
        assertEquals(ErrorKind.NOT_IMPLEMENTED, result.error.kind)
    }

    @Test
    fun `rate limiting on ut-v1 reads the header, or the problem field`() = runTest {
        val problem = ContractFixtures.utV1("response.RateLimited")
        server.dispatcher.override("ut/v1/me") {
            MockResponse(
                code = 429,
                headers = headersOf("Content-Type", "application/problem+json", "Retry-After", "5"),
                body = problem
            )
        }
        val withHeader = server.createApi(clock).me() as TunesResult.ApiError
        assertEquals(ErrorKind.RATE_LIMITED, withHeader.error.kind)
        assertEquals(Duration.ofSeconds(5), withHeader.error.retryAfter)

        server.dispatcher.override("ut/v1/me") {
            MockResponse(
                code = 429,
                headers = headersOf("Content-Type", "application/problem+json"),
                body = problem
            )
        }
        val withField = server.createApi(clock).me() as TunesResult.ApiError
        assertEquals(Duration.ofSeconds(60), withField.error.retryAfter)
    }

    @Test
    fun `every shared ut-v1 problem response maps to its code`() = runTest {
        val expected = mapOf(
            "response.BadRequest" to (ErrorKind.INVALID_ID to false),
            "response.Unauthorized" to (ErrorKind.INVALID_API_KEY to true),
            "response.Forbidden" to (ErrorKind.FORBIDDEN to false),
            "response.NotFound" to (ErrorKind.NOT_FOUND to false),
            "response.Conflict" to (ErrorKind.FEATURE_DISABLED to false),
            "response.TooLarge" to (ErrorKind.PAYLOAD_TOO_LARGE to false),
            "response.Upstream" to (ErrorKind.UPSTREAM_UNAVAILABLE to false),
            "response.NotImplemented" to (ErrorKind.NOT_IMPLEMENTED to false),
            "response.Internal" to (ErrorKind.INTERNAL to false)
        )
        val api = server.createApi(clock)
        expected.forEach { (fixture, outcome) ->
            val body = ContractFixtures.utV1(fixture)
            val status = Regex("\"status\":\\s*(\\d+)").find(body)!!.groupValues[1].toInt()
            server.dispatcher.override("ut/v1/listen-now") {
                MockResponse(
                    code = status,
                    headers = headersOf("Content-Type", "application/problem+json"),
                    body = body
                )
            }
            val result = api.listenNow()
            val (kind, unauthorized) = outcome
            val error = when (result) {
                is TunesResult.Unauthorized -> result.error.also {
                    assertTrue(unauthorized, fixture)
                }

                is TunesResult.ApiError -> result.error.also { assertFalse(unauthorized, fixture) }

                else -> error("$fixture gave $result")
            }
            assertEquals(kind, error.kind, fixture)
        }
    }

    @Test
    fun `a non-JSON 401 of a reverse proxy is unauthorized on both APIs`() = runTest {
        val page = MockResponse(
            code = 401,
            headers = headersOf("Content-Type", "text/html", "WWW-Authenticate", "Basic"),
            body = "<html>401 Authorization Required</html>"
        )
        server.dispatcher.override("rest/ping") { page }
        server.dispatcher.override("ut/v1/me") { page }
        val api = server.createApi(clock)
        val rest = api.ping()
        assertTrue(rest is TunesResult.Unauthorized, "$rest")
        assertEquals(401, (rest as TunesResult.Unauthorized).httpStatus)
        val ut = api.me()
        assertTrue(ut is TunesResult.Unauthorized, "$ut")
    }

    @Test
    fun `a malformed answer never repeats the body, which may hold a secret`() = runTest {
        val secret = FakeTunesServer.API_KEY
        server.dispatcher.override("ut/v1/keys") {
            MockResponse(
                code = 201,
                headers = headersOf("Content-Type", "application/json"),
                body = "{\"key\": 42, \"secret\": \"$secret\"}"
            )
        }
        server.dispatcher.override("rest/getSong") {
            json(
                200,
                "{\"subsonic-response\":{\"status\":\"ok\",\"song\":{\"title\":\"$secret\"}}}"
            )
        }
        val api = server.createApi(clock)
        val created = api.createKey(server.baseUrl, "alice", "pw", "Pixel 9")
        assertTrue(created is TunesResult.ProtocolError, "$created")
        created as TunesResult.ProtocolError
        assertEquals("Malformed response for ut/v1/keys", created.reason)
        assertFalse(created.toString().contains(secret))
        assertFalse(created.toString().contains("utk_"))

        val song = api.song(SongId("s")) as TunesResult.ProtocolError
        assertEquals("Malformed response for rest/getSong", song.reason)
        assertFalse(song.toString().contains(secret))
    }

    @Test
    fun `a non-JSON error page is a protocol error`() = runTest {
        server.dispatcher.override("ut/v1/me") {
            MockResponse(
                code = 502,
                headers = headersOf("Content-Type", "text/html"),
                body = "<html>Bad gateway</html>"
            )
        }
        server.dispatcher.override("rest/ping") {
            MockResponse(
                code = 502,
                headers = headersOf("Content-Type", "text/html"),
                body = "<html>Bad gateway</html>"
            )
        }
        val api = server.createApi(clock)
        assertEquals(502, (api.me() as TunesResult.ProtocolError).httpStatus)
        assertEquals(502, (api.ping() as TunesResult.ProtocolError).httpStatus)
    }

    @Test
    fun `malformed JSON is a protocol error`() = runTest {
        server.dispatcher.override("ut/v1/me") { json(200, "{\"id\": 1") }
        server.dispatcher.override("rest/getSong") {
            json(200, "{\"subsonic-response\":{\"status\":\"ok\",\"song\":{\"title\":\"no id\"}}}")
        }
        server.dispatcher.override("rest/getAlbum") {
            json(200, "{\"subsonic-response\":{\"status\":\"ok\"}}")
        }
        server.dispatcher.override("rest/ping") {
            json(200, "{\"subsonic-response\":{\"status\":\"failed\"}}")
        }
        server.dispatcher.override("rest/getArtists") { json(200, "[1, 2]") }
        server.dispatcher.override("ut/v1/search") {
            MockResponse(
                code = 400,
                headers = headersOf("Content-Type", "application/problem+json"),
                body = "{}"
            )
        }
        val api = server.createApi(clock)
        assertTrue(api.me() is TunesResult.ProtocolError)
        assertTrue(api.song(SongId("s")) is TunesResult.ProtocolError)
        assertTrue(api.album(AlbumId("a")) is TunesResult.ProtocolError)
        assertTrue(api.ping() is TunesResult.ProtocolError)
        assertTrue(api.artists() is TunesResult.ProtocolError)
        assertTrue(api.search("q") is TunesResult.ProtocolError)
    }

    @Test
    fun `optional payloads may be absent`() = runTest {
        val empty = "{\"subsonic-response\":{\"status\":\"ok\",\"version\":\"1.16.1\"}}"
        server.dispatcher.override("rest/getPlayQueue") { json(200, empty) }
        server.dispatcher.override("rest/getLyricsBySongId") { json(200, empty) }
        server.dispatcher.override("rest/getStarred2") { json(200, empty) }
        val api = server.createApi(clock)
        assertNull(api.playQueue().getOrNull())
        assertEquals(emptyList<Any>(), api.lyrics(SongId("s")).getOrNull())
        assertTrue(api.starred().getOrNull()!!.song.isEmpty())
    }

    @Test
    fun `no server is a network error`() = runTest {
        val api = server.createApi(clock)
        server.close()
        val rest = api.ping()
        assertTrue(rest is TunesResult.NetworkError, "$rest")
        assertFalse(rest.toString().contains(FakeTunesServer.API_KEY))
        assertTrue(api.me() is TunesResult.NetworkError)
    }

    @Test
    fun `without a configuration nothing is sent`() = runTest {
        val source = InMemoryServerConfigSource()
        val api = TunesApiFactory.create(TunesApiFactory.httpClient(source), source, clock)
        assertEquals(TunesResult.NotConfigured, api.ping())
        assertEquals(TunesResult.NotConfigured, api.me())
        assertEquals(
            TunesResult.NotConfigured,
            api.revokeKey(com.qtekfun.ultimatetunes.core.api.model.ApiKeyId("k"))
        )
        assertEquals(0, server.requestCount)

        // The Connect screen's calls take the URL explicitly.
        assertTrue(api.serverInfo("${server.baseUrl}?ignored=1".toHttpUrl()) is TunesResult.Success)
        assertEquals("/ut/v1/server", server.takeRequest().url.encodedPath)
    }

    @Test
    fun `a new configuration takes effect at once`() = runTest {
        val source =
            InMemoryServerConfigSource(server.serverConfig(apiKey = "utk_" + "y".repeat(43)))
        val api = TunesApiFactory.create(TunesApiFactory.httpClient(source), source, clock)
        assertTrue(api.ping() is TunesResult.Unauthorized)
        source.set(server.serverConfig())
        assertTrue(api.ping() is TunesResult.Success)
    }

    private fun problemBody(status: Int, code: String) =
        """{"type":"about:blank","title":"Error","status":$status,"code":"$code"}"""

    @Test
    fun `a non-admin key and a server without a cookie key are told apart`() = runTest {
        val api = server.createApi(clock)
        server.dispatcher.override("ut/v1/youtube-cookies") {
            MockResponse(
                code = 403,
                headers = headersOf("Content-Type", "application/problem+json"),
                body = problemBody(403, "forbidden")
            )
        }
        val forbidden = api.setYoutubeCookies("# Netscape HTTP Cookie File\n")
        assertEquals(ErrorKind.FORBIDDEN, (forbidden as TunesResult.ApiError).error.kind)
        assertEquals(403, forbidden.httpStatus)

        server.dispatcher.override("ut/v1/youtube-cookies") {
            MockResponse(
                code = 409,
                headers = headersOf("Content-Type", "application/problem+json"),
                body = problemBody(409, "feature_disabled")
            )
        }
        val disabled = api.setYoutubeCookies("# Netscape HTTP Cookie File\n")
        assertEquals(ErrorKind.FEATURE_DISABLED, (disabled as TunesResult.ApiError).error.kind)
    }

    @Test
    fun `the cookie text never appears in a protocol error`() = runTest {
        val api = server.createApi(clock)
        server.dispatcher.override("ut/v1/youtube-cookies") { json(200, "SECRET-COOKIE <html>") }
        val result = api.setYoutubeCookies("# Netscape HTTP Cookie File\nSECRET-COOKIE")
        assertTrue(result is TunesResult.ProtocolError, "$result")
        assertFalse(result.toString().contains("SECRET"))
    }
}
