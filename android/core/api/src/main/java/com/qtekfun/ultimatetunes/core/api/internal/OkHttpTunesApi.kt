// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api.internal

import com.qtekfun.ultimatetunes.core.api.ErrorKind
import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.ServerConfigSource
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesError
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.map
import com.qtekfun.ultimatetunes.core.api.model.Album
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.AlbumList2
import com.qtekfun.ultimatetunes.core.api.model.AlbumListType
import com.qtekfun.ultimatetunes.core.api.model.ApiKeyId
import com.qtekfun.ultimatetunes.core.api.model.ApiKeyList
import com.qtekfun.ultimatetunes.core.api.model.Artist
import com.qtekfun.ultimatetunes.core.api.model.ArtistId
import com.qtekfun.ultimatetunes.core.api.model.ArtistIndexes
import com.qtekfun.ultimatetunes.core.api.model.Charts
import com.qtekfun.ultimatetunes.core.api.model.CoverArtId
import com.qtekfun.ultimatetunes.core.api.model.CreateImportBody
import com.qtekfun.ultimatetunes.core.api.model.CreateKeyRequest
import com.qtekfun.ultimatetunes.core.api.model.CreatedKey
import com.qtekfun.ultimatetunes.core.api.model.Import
import com.qtekfun.ultimatetunes.core.api.model.ImportFileFormat
import com.qtekfun.ultimatetunes.core.api.model.ImportId
import com.qtekfun.ultimatetunes.core.api.model.ImportList
import com.qtekfun.ultimatetunes.core.api.model.ListenNow
import com.qtekfun.ultimatetunes.core.api.model.Lyrics
import com.qtekfun.ultimatetunes.core.api.model.LyricsList
import com.qtekfun.ultimatetunes.core.api.model.Me
import com.qtekfun.ultimatetunes.core.api.model.MoodTracks
import com.qtekfun.ultimatetunes.core.api.model.Moods
import com.qtekfun.ultimatetunes.core.api.model.PlayQueue
import com.qtekfun.ultimatetunes.core.api.model.Playlist
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.api.model.Playlists
import com.qtekfun.ultimatetunes.core.api.model.Problem
import com.qtekfun.ultimatetunes.core.api.model.Radio
import com.qtekfun.ultimatetunes.core.api.model.Recommendations
import com.qtekfun.ultimatetunes.core.api.model.RequestReason
import com.qtekfun.ultimatetunes.core.api.model.RequestTrackBody
import com.qtekfun.ultimatetunes.core.api.model.SearchResult
import com.qtekfun.ultimatetunes.core.api.model.ServerInfo
import com.qtekfun.ultimatetunes.core.api.model.Song
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.api.model.SongList
import com.qtekfun.ultimatetunes.core.api.model.Starred
import com.qtekfun.ultimatetunes.core.api.model.SubsonicStatus
import com.qtekfun.ultimatetunes.core.api.model.TrackStatus
import java.io.IOException
import java.time.Clock
import java.time.Duration
import java.time.Instant
import kotlinx.serialization.DeserializationStrategy
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import okhttp3.HttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody

/** One query parameter; repeatable parameters (`id`, `songId`…) are simply repeated. */
private typealias Param = Pair<String, String>

/**
 * [TunesApi] over OkHttp and kotlinx-serialization. [client] must carry the [AuthInterceptor] of
 * the same [configSource] (see `TunesApiModule`); this class never touches the key itself.
 */
@Suppress("TooManyFunctions") // One function per endpoint, as in TunesApi.
internal class OkHttpTunesApi(
    private val client: OkHttpClient,
    private val configSource: ServerConfigSource,
    private val clock: Clock,
    private val json: Json = TunesJson
) : TunesApi {

    // ---- /ut/v1 ----

    override suspend fun serverInfo(server: HttpUrl): TunesResult<ServerInfo> = utCall(
        root = ServerConfig.rootOf(server),
        path = listOf("server"),
        authenticated = false,
        decode = decoderOf(ServerInfo.serializer())
    )

    override suspend fun createKey(
        server: HttpUrl,
        username: String,
        password: String,
        deviceName: String
    ): TunesResult<CreatedKey> {
        val body = json.encodeToString(
            CreateKeyRequest.serializer(),
            CreateKeyRequest(username, password, deviceName)
        )
        return utCall(
            root = ServerConfig.rootOf(server),
            path = listOf("keys"),
            method = "POST",
            body = body.toJsonBody(),
            authenticated = false,
            decode = decoderOf(CreatedKey.serializer())
        )
    }

    override suspend fun me(): TunesResult<Me> = ut(Me.serializer(), "me")

    override suspend fun listKeys(): TunesResult<ApiKeyList> = ut(ApiKeyList.serializer(), "keys")

    override suspend fun revokeKey(id: ApiKeyId): TunesResult<Unit> =
        utUnit("keys", id.value, method = "DELETE")

    override suspend fun requestTrack(id: SongId, reason: RequestReason): TunesResult<TrackStatus> {
        val body = json.encodeToString(RequestTrackBody.serializer(), RequestTrackBody(reason))
        return ut(
            TrackStatus.serializer(),
            "tracks",
            id.value,
            "request",
            method = "POST",
            body = body.toJsonBody()
        )
    }

    override suspend fun trackStatus(id: SongId): TunesResult<TrackStatus> =
        ut(TrackStatus.serializer(), "tracks", id.value, "status")

    override suspend fun radio(seed: SongId, limit: Int?): TunesResult<Radio> =
        ut(Radio.serializer(), "radio", query = params("seed" to seed.value, "limit" to limit))

    override suspend fun search(
        query: String,
        limit: Int?,
        external: Boolean
    ): TunesResult<SearchResult> = ut(
        SearchResult.serializer(),
        "search",
        query = params("q" to query, "limit" to limit, "external" to external.takeUnless { it })
    )

    override suspend fun listenNow(): TunesResult<ListenNow> =
        ut(ListenNow.serializer(), "listen-now")

    override suspend fun recommendations(limit: Int?): TunesResult<Recommendations> =
        ut(Recommendations.serializer(), "recommendations", query = params("limit" to limit))

    override suspend fun charts(country: String?, limit: Int?): TunesResult<Charts> =
        ut(Charts.serializer(), "charts", query = params("country" to country, "limit" to limit))

    override suspend fun moods(): TunesResult<Moods> = ut(Moods.serializer(), "moods")

    override suspend fun moodTracks(id: String, limit: Int?): TunesResult<MoodTracks> =
        ut(MoodTracks.serializer(), "moods", id, query = params("limit" to limit))

    override suspend fun imports(limit: Int?, offset: Int?): TunesResult<List<Import>> =
        ut(ImportList.serializer(), "imports", query = params("limit" to limit, "offset" to offset))
            .map { it.imports }

    override suspend fun createImport(url: String, name: String?): TunesResult<Import> {
        val body = json.encodeToString(CreateImportBody.serializer(), CreateImportBody(url, name))
        return ut(Import.serializer(), "imports", method = "POST", body = body.toJsonBody())
    }

    override suspend fun createFileImport(
        content: ByteArray,
        fileName: String,
        format: ImportFileFormat,
        name: String?
    ): TunesResult<Import> {
        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart(
                "file",
                fileName,
                content.toRequestBody(format.mediaType.toMediaType())
            )
            .addFormDataPart("format", format.wireName)
            .apply { if (name != null) addFormDataPart("name", name) }
            .build()
        return ut(Import.serializer(), "imports", method = "POST", body = body)
    }

    override suspend fun import(id: ImportId): TunesResult<Import> =
        ut(Import.serializer(), "imports", id.value)

    // ---- OpenSubsonic ----

    override suspend fun ping(): TunesResult<Unit> = restUnit("ping")

    override suspend fun artists(): TunesResult<ArtistIndexes> =
        rest("getArtists", emptyList()) { it.field("artists", ArtistIndexes.serializer()) }

    override suspend fun artist(id: ArtistId): TunesResult<Artist> =
        rest("getArtist", params("id" to id.value)) { it.field("artist", Artist.serializer()) }

    override suspend fun album(id: AlbumId): TunesResult<Album> =
        rest("getAlbum", params("id" to id.value)) { it.field("album", Album.serializer()) }

    override suspend fun song(id: SongId): TunesResult<Song> =
        rest("getSong", params("id" to id.value)) { it.field("song", Song.serializer()) }

    override suspend fun albumList(
        type: AlbumListType,
        size: Int?,
        offset: Int?,
        fromYear: Int?,
        toYear: Int?,
        genre: String?
    ): TunesResult<List<Album>> {
        val query = params(
            "type" to type.wireName,
            "size" to size,
            "offset" to offset,
            "fromYear" to fromYear,
            "toYear" to toYear,
            "genre" to genre
        )
        return rest("getAlbumList2", query) {
            it.field("albumList2", AlbumList2.serializer()).album
        }
    }

    override suspend fun randomSongs(size: Int?, genre: String?): TunesResult<List<Song>> =
        rest("getRandomSongs", params("size" to size, "genre" to genre)) {
            it.field("randomSongs", SongList.serializer()).song
        }

    override suspend fun similarSongs(id: SongId, count: Int?): TunesResult<List<Song>> =
        rest("getSimilarSongs2", params("id" to id.value, "count" to count)) {
            it.field("similarSongs2", SongList.serializer()).song
        }

    override suspend fun lyrics(id: SongId): TunesResult<List<Lyrics>> =
        rest("getLyricsBySongId", params("id" to id.value)) {
            it.optionalField("lyricsList", LyricsList.serializer())?.structuredLyrics.orEmpty()
        }

    override suspend fun playlists(): TunesResult<List<Playlist>> =
        rest("getPlaylists", emptyList()) { it.field("playlists", Playlists.serializer()).playlist }

    override suspend fun playlist(id: PlaylistId): TunesResult<Playlist> =
        rest("getPlaylist", params("id" to id.value)) {
            it.field("playlist", Playlist.serializer())
        }

    override suspend fun createPlaylist(
        name: String,
        songIds: List<SongId>
    ): TunesResult<Playlist> =
        rest("createPlaylist", params("name" to name) + songIds.map { "songId" to it.value }) {
            it.field("playlist", Playlist.serializer())
        }

    override suspend fun updatePlaylist(
        id: PlaylistId,
        name: String?,
        comment: String?,
        public: Boolean?,
        songIdsToAdd: List<SongId>,
        songIndexesToRemove: List<Int>
    ): TunesResult<Unit> = restUnit(
        "updatePlaylist",
        params("playlistId" to id.value, "name" to name, "comment" to comment, "public" to public) +
            songIdsToAdd.map { "songIdToAdd" to it.value } +
            songIndexesToRemove.map { "songIndexToRemove" to it.toString() }
    )

    override suspend fun deletePlaylist(id: PlaylistId): TunesResult<Unit> =
        restUnit("deletePlaylist", params("id" to id.value))

    override suspend fun star(
        songIds: List<SongId>,
        albumIds: List<AlbumId>,
        artistIds: List<ArtistId>
    ): TunesResult<Unit> = restUnit("star", starParams(songIds, albumIds, artistIds))

    override suspend fun unstar(
        songIds: List<SongId>,
        albumIds: List<AlbumId>,
        artistIds: List<ArtistId>
    ): TunesResult<Unit> = restUnit("unstar", starParams(songIds, albumIds, artistIds))

    override suspend fun starred(): TunesResult<Starred> = rest("getStarred2", emptyList()) {
        it.optionalField("starred2", Starred.serializer())
            ?: Starred()
    }

    override suspend fun scrobble(
        id: SongId,
        submission: Boolean,
        playedAt: Instant?
    ): TunesResult<Unit> {
        val time = (playedAt ?: clock.instant()).toEpochMilli()
        return restUnit(
            "scrobble",
            params(
                "id" to id.value,
                "time" to time,
                "submission" to submission
            )
        )
    }

    override suspend fun playQueue(): TunesResult<PlayQueue?> =
        rest("getPlayQueue", emptyList()) { it.optionalField("playQueue", PlayQueue.serializer()) }

    override suspend fun savePlayQueue(
        ids: List<SongId>,
        current: SongId?,
        positionMillis: Long?
    ): TunesResult<Unit> = restUnit(
        "savePlayQueue",
        ids.map { "id" to it.value } +
            params("current" to current?.value, "position" to positionMillis)
    )

    // ---- URLs ----

    override fun streamUrl(id: SongId): HttpUrl? = restUrl("stream", params("id" to id.value))

    override fun downloadUrl(id: SongId): HttpUrl? = restUrl("download", params("id" to id.value))

    override fun coverArtUrl(id: CoverArtId, size: Int?): HttpUrl? =
        restUrl("getCoverArt", params("id" to id.value, "size" to size))

    // ---- plumbing: OpenSubsonic ----

    private fun restUrl(endpoint: String, query: List<Param>): HttpUrl? =
        configSource.config.value?.let { buildUrl(it.root, listOf(REST, endpoint), query) }

    private suspend fun restUnit(
        endpoint: String,
        query: List<Param> = emptyList()
    ): TunesResult<Unit> = rest(endpoint, query) { }

    /**
     * `GET /rest/<endpoint>` and the `subsonic-response` it returns: [decode] reads the payload of
     * an `ok` answer; a `failed` one, or HTTP 429/501, becomes the mapped error.
     */
    private suspend fun <T> rest(
        endpoint: String,
        query: List<Param>,
        decode: (JsonObject) -> T
    ): TunesResult<T> {
        val url = restUrl(endpoint, query) ?: return TunesResult.NotConfigured
        return exchange(Request.Builder().url(url).get().build()) { answer ->
            val envelope = envelopeOf(answer.body)
            if (envelope == null) {
                withoutDocument(answer, "rest/$endpoint", "subsonic-response")
            } else {
                decodeEnvelope(envelope, answer, "rest/$endpoint", decode)
            }
        }
    }

    /** The `subsonic-response` object of [body], or null when there is none. */
    private fun envelopeOf(body: String): JsonObject? = try {
        json.parseToJsonElement(body).jsonObject[ENVELOPE]?.jsonObject
    } catch (_: SerializationException) {
        null
    } catch (_: IllegalArgumentException) {
        null
    }

    /** Sends [request]; a network failure becomes [TunesResult.NetworkError], an answer goes to [handle]. */
    private suspend fun <T> exchange(
        request: Request,
        handle: (HttpAnswer) -> TunesResult<T>
    ): TunesResult<T> {
        val answer = try {
            client.newCall(request).await()
        } catch (e: IOException) {
            return TunesResult.NetworkError(e)
        }
        return handle(answer)
    }

    private fun <T> decodeEnvelope(
        envelope: JsonObject,
        answer: HttpAnswer,
        operation: String,
        decode: (JsonObject) -> T
    ): TunesResult<T> = readable(answer, operation) {
        val status = json.decodeFromJsonElement(SubsonicStatus.serializer(), envelope)
        val error = status.error
        when {
            status.status == STATUS_OK && answer.isSuccessful -> TunesResult.Success(
                decode(envelope)
            )

            error != null -> ErrorMapping.failure(
                TunesError(
                    kind = ErrorMapping.subsonicKind(error.code, answer.code),
                    message = error.message,
                    code = error.code.toString(),
                    retryAfter = ErrorMapping.retryAfter(answer.retryAfter, clock),
                    helpUrl = error.helpUrl
                ),
                answer.code
            )

            else -> TunesResult.ProtocolError(
                "Status '${status.status}' without an error",
                answer.code
            )
        }
    }

    private fun <T> JsonObject.field(name: String, deserializer: DeserializationStrategy<T>): T =
        optionalField(name, deserializer) ?: throw SerializationException("Missing '$name'")

    private fun <T> JsonObject.optionalField(
        name: String,
        deserializer: DeserializationStrategy<T>
    ): T? = get(name)?.let { json.decodeFromJsonElement(deserializer, it) }

    private fun starParams(
        songs: List<SongId>,
        albums: List<AlbumId>,
        artists: List<ArtistId>
    ): List<Param> = songs.map { "id" to it.value } +
        albums.map { "albumId" to it.value } +
        artists.map { "artistId" to it.value }

    // ---- plumbing: /ut/v1 ----

    /** A `/ut/v1` call on the configured server, decoding the answer with [deserializer]. */
    private suspend fun <T> ut(
        deserializer: DeserializationStrategy<T>,
        vararg path: String,
        method: String = "GET",
        body: RequestBody? = null,
        query: List<Param> = emptyList()
    ): TunesResult<T> {
        val config = configSource.config.value ?: return TunesResult.NotConfigured
        return utCall(
            config.root,
            path.toList(),
            method,
            body,
            query,
            decode = decoderOf(deserializer)
        )
    }

    /** A `/ut/v1` call on the configured server whose answer has no body (204). */
    private suspend fun utUnit(vararg path: String, method: String): TunesResult<Unit> {
        val config = configSource.config.value ?: return TunesResult.NotConfigured
        return utCall(config.root, path.toList(), method, decode = IGNORE_BODY)
    }

    private fun <T> decoderOf(deserializer: DeserializationStrategy<T>): (String) -> T =
        { text -> json.decodeFromString(deserializer, text) }

    @Suppress("LongParameterList") // Internal plumbing with defaults; callers name the arguments.
    private suspend fun <T> utCall(
        root: HttpUrl,
        path: List<String>,
        method: String = "GET",
        body: RequestBody? = null,
        query: List<Param> = emptyList(),
        authenticated: Boolean = true,
        decode: (String) -> T
    ): TunesResult<T> {
        val request = Request.Builder()
            .url(buildUrl(root, UT_PATH + path, query))
            .method(method, body)
            .header("Accept", "application/json, application/problem+json")
            .apply { if (!authenticated) tag(NoAuth::class.java, NoAuth) }
            .build()
        val operation = (UT_PATH + path.first()).joinToString("/")
        return exchange(request) { answer ->
            readable(answer, operation) {
                if (answer.isSuccessful) {
                    TunesResult.Success(decode(answer.body))
                } else {
                    problem(answer, operation)
                }
            }
        }
    }

    /**
     * Runs [read]; JSON that does not match the models becomes [TunesResult.ProtocolError] with a
     * fixed reason. The parser's message is dropped on purpose: it quotes the body, which can hold
     * a secret (the new key of `POST /ut/v1/keys`).
     */
    private inline fun <T> readable(
        answer: HttpAnswer,
        operation: String,
        read: () -> TunesResult<T>
    ): TunesResult<T> = try {
        read()
    } catch (_: SerializationException) {
        TunesResult.ProtocolError("Malformed response for $operation", answer.code)
    } catch (_: IllegalArgumentException) {
        TunesResult.ProtocolError("Malformed response for $operation", answer.code)
    }

    /**
     * An answer without the expected [document] (an HTML page of a reverse proxy, say). A 401 is
     * still a credential problem, so it is [TunesResult.Unauthorized] on both APIs.
     */
    private fun withoutDocument(
        answer: HttpAnswer,
        operation: String,
        document: String
    ): TunesResult.Failure = if (answer.code == ErrorMapping.HTTP_UNAUTHORIZED) {
        ErrorMapping.failure(
            TunesError(ErrorKind.UNKNOWN, "HTTP 401 without a $document"),
            answer.code
        )
    } else {
        TunesResult.ProtocolError(
            "HTTP ${answer.code} without a $document for $operation",
            answer.code
        )
    }

    private fun problem(answer: HttpAnswer, operation: String): TunesResult.Failure {
        if (answer.contentType?.contains("json") != true) {
            return withoutDocument(answer, operation, "problem document")
        }
        val problem = json.decodeFromString(Problem.serializer(), answer.body)
        val retryAfter = ErrorMapping.retryAfter(answer.retryAfter, clock)
            ?: problem.retryAfter?.let { Duration.ofSeconds(it) }
        return ErrorMapping.failure(
            TunesError(
                kind = ErrorMapping.problemKind(problem.code),
                message = problem.detail ?: problem.title,
                code = problem.code,
                retryAfter = retryAfter
            ),
            answer.code
        )
    }

    // ---- helpers ----

    private fun buildUrl(root: HttpUrl, segments: List<String>, query: List<Param>): HttpUrl =
        root.newBuilder().apply {
            segments.forEach { addPathSegment(it) }
            query.forEach { (name, value) -> addQueryParameter(name, value) }
        }.build()

    private fun String.toJsonBody(): RequestBody = toRequestBody(JSON_MEDIA_TYPE)

    private companion object {
        const val REST = "rest"
        const val ENVELOPE = "subsonic-response"
        const val STATUS_OK = "ok"
        val UT_PATH = listOf("ut", "v1")
        val IGNORE_BODY: (String) -> Unit = {}
        val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()

        /** Parameters with a value; null ones are left out. */
        fun params(vararg pairs: Pair<String, Any?>): List<Param> =
            pairs.mapNotNull { (name, value) -> value?.let { name to it.toString() } }
    }
}

/** The JSON settings of both APIs: unknown properties ignored, nulls omitted when sending. */
internal val TunesJson: Json = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
}
