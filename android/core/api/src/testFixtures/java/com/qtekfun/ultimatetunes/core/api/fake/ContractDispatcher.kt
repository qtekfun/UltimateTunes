// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api.fake

import java.net.URLDecoder
import java.util.concurrent.ConcurrentHashMap
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import mockwebserver3.Dispatcher
import mockwebserver3.MockResponse
import mockwebserver3.RecordedRequest
import okhttp3.Headers.Companion.headersOf
import okio.Buffer

/**
 * A MockWebServer [Dispatcher] that answers every endpoint the app uses, with the contract
 * examples ([ContractFixtures]) as bodies and the contracts' authentication rules:
 * - `/rest/…`: `apiKey` (also form POST and the `.view` suffix), the key as password (`u` + `p`,
 *   also `enc:`), token auth refused with 42, mixed mechanisms with 43, unknown key 44, wrong
 *   password 40, no credentials 10. HTTP 200 envelopes, as the server sends them.
 * - `/ut/v1/…`: the `X-Api-Key` header or the `apiKey` parameter; `GET server` and `POST keys` are
 *   public. Errors are problem documents.
 *
 * Tests steer it with [trackStatusExample], [importExample] and [override] (for errors, delays or
 * custom data); everything else is fixed by the contracts.
 */
class ContractDispatcher(private val apiKey: String = FakeTunesServer.API_KEY) : Dispatcher() {
    /** Which `getTrackStatus` example to serve: `downloading`, `ready`, `failed`, `notRequested`. */
    @Volatile
    var trackStatusExample: String = "ready"

    /** Which `getImport` example to serve: `queued` or `done`. */
    @Volatile
    var importExample: String = "done"

    private val overrides = ConcurrentHashMap<String, (RecordedRequest) -> MockResponse>()

    /**
     * Answers [endpoint] (`rest/getAlbum`, `ut/v1/search`, `ut/v1/tracks/{id}/status` with the
     * real id) with [handler] instead of the contract example, until [clearOverrides].
     */
    fun override(endpoint: String, handler: (RecordedRequest) -> MockResponse) {
        overrides[endpoint.trim('/')] = handler
    }

    fun clearOverrides() {
        overrides.clear()
    }

    override fun dispatch(request: RecordedRequest): MockResponse {
        val path = request.url.pathSegments.joinToString("/").removeSuffix(".view")
        overrides[path]?.let { return it(request) }
        val segments = path.split('/')
        return when {
            segments.first() == "rest" && segments.size == 2 -> Rest(request).answer(segments[1])
            segments.take(2) == listOf("ut", "v1") -> Ut(request).answer(segments.drop(2))
            else -> MockResponse(code = 404)
        }
    }

    // ---- OpenSubsonic ----

    private inner class Rest(private val request: RecordedRequest) {
        private val params: Map<String, List<String>> = queryAndForm(request)

        fun param(name: String): String? = params[name]?.firstOrNull()

        fun answer(endpoint: String): MockResponse {
            if (endpoint !in PUBLIC_REST) authFailure()?.let { return it }
            if (endpoint in ID_REQUIRED &&
                param("id").isNullOrEmpty()
            ) {
                return missingParameter("id")
            }
            return when (endpoint) {
                "stream", "download" -> audio(param("id").orEmpty())

                "getCoverArt" -> image()

                in SIMPLE_REST -> envelope(rest("${endpoint}_ok"))

                else -> MockResponse(
                    code = 501,
                    headers = JSON_HEADERS,
                    body = rest("response.NotImplemented")
                )
            }
        }

        /** The failure envelope for these credentials, or null when they are good. */
        private fun authFailure(): MockResponse? {
            val key = param("apiKey")
            val legacy = listOf("u", "p", "t", "s").filter { param(it) != null }
            return when {
                key != null && legacy.isNotEmpty() -> failure(
                    43,
                    "Conflicting authentication mechanisms"
                )

                param(
                    "t"
                ) != null || param(
                    "s"
                ) != null -> failure(42, "Token authentication is not supported")

                key != null -> if (key == apiKey) null else envelope(rest("failed_invalidApiKey"))

                param("u") != null && param("p") != null -> if (password(param("p")!!) == apiKey) {
                    null
                } else {
                    envelope(rest("failed_wrongPassword"))
                }

                else -> missingParameter("apiKey")
            }
        }

        private fun password(p: String): String = if (p.startsWith("enc:")) {
            p.removePrefix("enc:").chunked(2).map {
                it.toInt(HEX).toChar()
            }.joinToString("")
        } else {
            p
        }

        private fun missingParameter(name: String) =
            failure(10, "Required parameter is missing: $name")

        /** A failed envelope with [code], shaped like the contract's failure examples. */
        private fun failure(code: Int, message: String): MockResponse {
            val template = Json.parseToJsonElement(rest("failed_wrongPassword")).jsonObject
            val body = template.withEnvelope { envelope ->
                JsonObject(
                    envelope + (
                        "error" to buildJsonObject {
                            put("code", code)
                            put("message", message)
                        }
                        )
                )
            }
            return envelope(body.toString())
        }

        private fun audio(id: String): MockResponse = if (id.startsWith("yt:")) {
            // A song still downloading: chunked, no length, no seek (contract of `stream`).
            MockResponse.Builder()
                .addHeader("Content-Type", "audio/ogg")
                .addHeader("Accept-Ranges", "none")
                .chunkedBody(Buffer().write(FAKE_AUDIO), FAKE_AUDIO.size / 2)
                .build()
        } else {
            MockResponse.Builder()
                .addHeader("Content-Type", "audio/ogg")
                .addHeader("Accept-Ranges", "bytes")
                .body(Buffer().write(FAKE_AUDIO))
                .build()
        }

        private fun image(): MockResponse = MockResponse.Builder()
            .addHeader("Content-Type", "image/png")
            .body(Buffer().write(PNG_1X1))
            .build()
    }

    // ---- /ut/v1 ----

    private inner class Ut(private val request: RecordedRequest) {
        private val method = request.method

        fun answer(path: List<String>): MockResponse {
            val public =
                (path == listOf("server") && method == "GET") ||
                    (path == listOf("keys") && method == "POST")
            if (!public) authFailure()?.let { return it }
            return route(path) ?: problem(404, "not_found", "Not found", "No such resource")
        }

        private fun route(path: List<String>): MockResponse? {
            // `tracks/yt:Qx7Lm2pZ0aB/status` -> `tracks/*/status`
            val pattern = path.mapIndexed { i, segment -> if (i == 1) "*" else segment }
            val id = path.getOrNull(1).orEmpty()
            return when ("$method ${pattern.joinToString("/")}") {
                "GET server" -> ok(ut("getServerInfo.200"))

                "GET me" -> ok(ut("getMe.200"))

                "GET keys" -> ok(ut("listKeys.200"))

                "POST keys" -> createKey()

                "DELETE keys/*" -> MockResponse(code = 204)

                "POST tracks/*/request" -> requestTrack(id)

                "GET tracks/*/status" ->
                    validId(id) ?: ok(ut("getTrackStatus.200.$trackStatusExample"))

                "GET radio" -> required("seed") ?: radio()

                "GET search" -> required("q") ?: ok(ut("search.200"))

                "GET listen-now" -> ok(ut("getListenNow.200"))

                "GET recommendations" -> ok(ut("getRecommendations.200"))

                "GET charts" -> ok(ut("getCharts.200"))

                "GET moods" -> ok(ut("getMoods.200"))

                "GET moods/*" -> ok(ut("getMoodTracks.200"))

                "GET imports" -> ok(ut("listImports.200"))

                "POST imports" -> createImport()

                "GET imports/*" -> ok(ut("getImport.200.$importExample"))

                else -> null
            }
        }

        private fun radio(): MockResponse =
            validId(request.url.queryParameter("seed").orEmpty()) ?: ok(ut("getRadio.200"))

        /**
         * A URL import (JSON) answers the contract example; a file import (multipart) the same
         * example with its `source` and a null `sourceUrl`. Spotify URLs are `unsupported_url`.
         */
        private fun createImport(): MockResponse {
            val text = request.body?.utf8().orEmpty()
            val multipart = request.headers["Content-Type"].orEmpty().startsWith("multipart/")
            val example = Json.parseToJsonElement(ut("createImport.202")).jsonObject
            val format = formField(text, "format")
            val invalid = if (multipart) fileImportError(text, format) else urlImportError(text)
            val body = if (multipart) {
                JsonObject(
                    example + mapOf("source" to JsonPrimitive(format), "sourceUrl" to JsonNull)
                )
            } else {
                example
            }
            val location = "/ut/v1/imports/" + example.getValue("id").jsonPrimitive.content
            return invalid ?: MockResponse(
                code = 202,
                headers = headersOf("Content-Type", JSON, "Location", location),
                body = body.toString()
            )
        }

        private fun fileImportError(text: String, format: String?): MockResponse? = when {
            formField(text, "file") == null -> missing("file")

            format == null -> missing("format")

            format !in FILE_FORMATS ->
                problem(400, "invalid_parameter", "Invalid parameter", "Unknown format '$format'")

            else -> null
        }

        private fun urlImportError(text: String): MockResponse? {
            val url = Json.parseToJsonElement(
                text.ifEmpty {
                    "{}"
                }
            ).jsonObject["url"]?.jsonPrimitive?.content
            return when {
                url == null -> missing("url")

                !YOUTUBE_PLAYLIST.containsMatchIn(url) ->
                    problem(400, "unsupported_url", "Unsupported URL", "Not a YouTube playlist URL")

                else -> null
            }
        }

        private fun missing(name: String) =
            problem(400, "missing_parameter", "Missing parameter", "'$name' is required")

        private fun authFailure(): MockResponse? {
            val header = request.headers["X-Api-Key"]
            val query = request.url.queryParameter("apiKey")
            return when {
                header != null && query != null && header != query ->
                    problem(
                        400,
                        "conflicting_auth",
                        "Conflicting authentication",
                        "X-Api-Key and apiKey differ"
                    )

                header == null && query == null ->
                    problem(
                        401,
                        "authentication_required",
                        "Authentication required",
                        "Send X-Api-Key"
                    )

                (header ?: query) != apiKey -> MockResponse(
                    code = 401,
                    headers = PROBLEM_HEADERS,
                    body = ut("response.Unauthorized")
                )

                else -> null
            }
        }

        private fun createKey(): MockResponse {
            val body = request.body?.utf8()?.let { Json.parseToJsonElement(it).jsonObject }
            val username = body?.get("username")?.jsonPrimitive?.content
            val password = body?.get("password")?.jsonPrimitive?.content
            return if (username == FakeTunesServer.USERNAME &&
                password == FakeTunesServer.PASSWORD
            ) {
                MockResponse(
                    code = 201,
                    headers = headersOf("Content-Type", JSON, "Cache-Control", "no-store"),
                    body = ut("createKey.201")
                )
            } else {
                problem(
                    401,
                    "authentication_failed",
                    "Authentication failed",
                    "Wrong username or password"
                )
            }
        }

        private fun requestTrack(id: String): MockResponse =
            validId(id) ?: if (id.startsWith("yt:")) {
                MockResponse(
                    code = 202,
                    headers = JSON_HEADERS,
                    body = ut("requestTrack.202.queued")
                )
            } else {
                ok(ut("requestTrack.200"))
            }

        private fun required(name: String): MockResponse? =
            if (request.url.queryParameter(name).isNullOrEmpty()) {
                problem(400, "missing_parameter", "Missing parameter", "'$name' is required")
            } else {
                null
            }

        /** The contract's `invalid_id` problem for a malformed virtual id (contracts/ids.md). */
        private fun validId(id: String): MockResponse? = if (id.startsWith("yt:") &&
            !VIDEO_ID.matches(id.removePrefix("yt:"))
        ) {
            MockResponse(code = 400, headers = PROBLEM_HEADERS, body = ut("response.BadRequest"))
        } else {
            null
        }

        private fun ok(body: String) = MockResponse(code = 200, headers = JSON_HEADERS, body = body)

        /** A problem document shaped like the contract's examples. */
        private fun problem(
            status: Int,
            code: String,
            title: String,
            detail: String
        ): MockResponse {
            val body = buildJsonObject {
                put(
                    "type",
                    "https://github.com/qtekfun/UltimateTunes/blob/master/contracts/errors.md#$code"
                )
                put("title", title)
                put("status", status)
                put("detail", detail)
                put("code", code)
                put("instance", "/" + request.url.encodedPath.trimStart('/'))
            }
            return MockResponse(code = status, headers = PROBLEM_HEADERS, body = body.toString())
        }
    }

    private companion object {
        const val JSON = "application/json"
        const val HEX = 16
        val JSON_HEADERS = headersOf("Content-Type", JSON)
        val PROBLEM_HEADERS = headersOf("Content-Type", "application/problem+json")
        val VIDEO_ID = Regex("^[A-Za-z0-9_-]{11}$")
        val FILE_FORMATS = setOf("csv", "exportify_csv", "spotify_json")
        val YOUTUBE_PLAYLIST =
            Regex(
                "^https://(music\\.youtube\\.com|www\\.youtube\\.com|youtube\\.com|m\\.youtube\\.com)/.*[?&]list="
            )

        /** The value of the multipart field [name] (for a file part: its content), or null. */
        fun formField(body: String, name: String): String? {
            val part =
                Regex(
                    "Content-Disposition: form-data; name=\"$name\"[^\r\n]*\r\n(?:[^\r\n]+\r\n)*\r\n"
                )
            val start = part.find(body)?.range?.last?.plus(1) ?: return null
            val end = body.indexOf("\r\n--", start)
            return if (end < 0) null else body.substring(start, end)
        }

        /** Endpoints without credentials. */
        val PUBLIC_REST = setOf("getOpenSubsonicExtensions")

        /** Endpoints whose `id` parameter is required. */
        val ID_REQUIRED = setOf(
            "getArtist",
            "getAlbum",
            "getSong",
            "getLyricsBySongId",
            "getPlaylist",
            "deletePlaylist",
            "getSimilarSongs2",
            "getCoverArt",
            "stream",
            "download"
        )

        /** Endpoints answered with their `<endpoint>_ok` example. */
        val SIMPLE_REST = setOf(
            "ping",
            "getLicense",
            "getOpenSubsonicExtensions",
            "tokenInfo",
            "getMusicFolders",
            "getArtists",
            "getArtist",
            "getAlbum",
            "getSong",
            "getAlbumList2",
            "getRandomSongs",
            "search3",
            "getLyricsBySongId",
            "getPlaylists",
            "getPlaylist",
            "createPlaylist",
            "updatePlaylist",
            "deletePlaylist",
            "star",
            "unstar",
            "getStarred2",
            "scrobble",
            "getSimilarSongs2",
            "getPlayQueue",
            "savePlayQueue"
        )

        /** Not a real Opus file: just recognisable bytes for the player tests to compare. */
        val FAKE_AUDIO: ByteArray = "OggS-fake-ultimatetunes-audio".encodeToByteArray()

        /** A valid 1x1 transparent PNG, so an image loader can decode it. */
        val PNG_1X1: ByteArray = intArrayOf(
            0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00, 0x00, 0x0D,
            0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
            0x08, 0x06, 0x00, 0x00, 0x00, 0x1F, 0x15, 0xC4, 0x89, 0x00, 0x00, 0x00,
            0x0D, 0x49, 0x44, 0x41, 0x54, 0x78, 0xDA, 0x63, 0x60, 0x60, 0x60, 0x60,
            0x00, 0x00, 0x00, 0x05, 0x00, 0x01, 0x7A, 0xA8, 0x57, 0x50, 0x00, 0x00,
            0x00, 0x00, 0x49, 0x45, 0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82
        ).map { it.toByte() }.toByteArray()

        fun rest(name: String) = ContractFixtures.openSubsonic(name)

        fun ut(name: String) = ContractFixtures.utV1(name)

        fun envelope(body: String) = MockResponse(code = 200, headers = JSON_HEADERS, body = body)

        fun JsonObject.withEnvelope(transform: (JsonObject) -> JsonObject): JsonObject {
            val envelope = getValue("subsonic-response").jsonObject
            return JsonObject(this + ("subsonic-response" to transform(envelope)))
        }

        /** Query parameters, plus the form body of a `formPost` request. */
        fun queryAndForm(request: RecordedRequest): Map<String, List<String>> {
            val all = mutableMapOf<String, MutableList<String>>()
            request.url.queryParameterNames.forEach { name ->
                all.getOrPut(name) { mutableListOf() } +=
                    request.url.queryParameterValues(name).filterNotNull()
            }
            val contentType = request.headers["Content-Type"].orEmpty()
            if (contentType.startsWith("application/x-www-form-urlencoded")) {
                request.body?.utf8()?.split('&')?.filter { it.isNotEmpty() }?.forEach { pair ->
                    val name = URLDecoder.decode(pair.substringBefore('='), "UTF-8")
                    val value = URLDecoder.decode(pair.substringAfter('=', ""), "UTF-8")
                    all.getOrPut(name) { mutableListOf() } += value
                }
            }
            return all
        }
    }
}
