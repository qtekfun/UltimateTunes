// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.demo

import com.qtekfun.ultimatetunes.core.api.model.Album
import com.qtekfun.ultimatetunes.core.api.model.ApiKey
import com.qtekfun.ultimatetunes.core.api.model.ApiKeyId
import com.qtekfun.ultimatetunes.core.api.model.ApiKeyList
import com.qtekfun.ultimatetunes.core.api.model.Artist
import com.qtekfun.ultimatetunes.core.api.model.ArtistIndex
import com.qtekfun.ultimatetunes.core.api.model.ArtistIndexes
import com.qtekfun.ultimatetunes.core.api.model.Capabilities
import com.qtekfun.ultimatetunes.core.api.model.Import
import com.qtekfun.ultimatetunes.core.api.model.ImportList
import com.qtekfun.ultimatetunes.core.api.model.ImportSource
import com.qtekfun.ultimatetunes.core.api.model.ListenNow
import com.qtekfun.ultimatetunes.core.api.model.Lyrics
import com.qtekfun.ultimatetunes.core.api.model.Me
import com.qtekfun.ultimatetunes.core.api.model.OpenSubsonicInfo
import com.qtekfun.ultimatetunes.core.api.model.PlayQueue
import com.qtekfun.ultimatetunes.core.api.model.Playlist
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.api.model.Radio
import com.qtekfun.ultimatetunes.core.api.model.Role
import com.qtekfun.ultimatetunes.core.api.model.SearchResult
import com.qtekfun.ultimatetunes.core.api.model.ServerInfo
import com.qtekfun.ultimatetunes.core.api.model.Song
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.api.model.Starred
import com.qtekfun.ultimatetunes.core.api.model.TrackState
import com.qtekfun.ultimatetunes.core.api.model.TrackStatus
import com.qtekfun.ultimatetunes.core.api.model.UserId
import com.qtekfun.ultimatetunes.demo.DemoCatalog.toAlbumItem
import com.qtekfun.ultimatetunes.demo.DemoCatalog.toArtistItem
import com.qtekfun.ultimatetunes.demo.DemoCatalog.toTrackItem
import java.net.URLDecoder
import java.time.Clock
import kotlinx.serialization.KSerializer
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObjectBuilder
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import mockwebserver3.Dispatcher
import mockwebserver3.MockResponse
import mockwebserver3.RecordedRequest
import okhttp3.Headers.Companion.headersOf
import okio.Buffer

/**
 * The demo server's answers: every endpoint of `TunesApi` over [DemoCatalog], with the key
 * [apiKey] required like a real server. Playlists, favourites and the play queue live in memory
 * until the app is closed. [artwork] draws covers (Android graphics, swapped in unit tests).
 */
@Suppress("TooManyFunctions", "MagicNumber") // One function per endpoint; HTTP and Subsonic codes.
internal class DemoDispatcher(
    private val apiKey: String,
    private val clock: Clock,
    private val artwork: (label: String, size: Int?) -> ByteArray = DemoArtwork::png
) : Dispatcher() {
    private val json = Json {
        explicitNulls = false
        encodeDefaults = false
    }
    private val startedAt = clock.instant()
    private val lock = Any()
    private val playlists = DemoPlaylists.initial(startedAt).toMutableList()
    private val imports = DemoImports(clock) { done ->
        createPlaylist(
            done.name ?: "Imported Playlist",
            done.items.mapNotNull {
                it.track?.id?.value
            }
        ).id
    }
    private val starredSongs = DemoCatalog.mostPlayed.take(4).map { it.id.value }.toMutableSet()
    private var playQueue: PlayQueue? = null

    override fun dispatch(request: RecordedRequest): MockResponse {
        val segments = request.url.pathSegments.filter { it.isNotEmpty() }
        return when {
            segments.size == 2 && segments[0] == "rest" ->
                rest(segments[1].removeSuffix(".view"), request)

            segments.take(
                2
            ) == listOf("ut", "v1") -> ut(request.method.orEmpty(), segments.drop(2), request)

            else -> MockResponse(code = 404)
        }
    }

    // ---- /ut/v1 ----

    private fun ut(method: String, path: List<String>, request: RecordedRequest): MockResponse {
        val route = "$method ${path.mapIndexed { i, s ->
            if (i == 1) "*" else s
        }.joinToString("/")}"
        return when {
            route == "GET server" -> ok(ServerInfo.serializer(), serverInfo())

            request.headers["X-Api-Key"] != apiKey ->
                problem(401, "invalid_api_key", "The demo key is the only one accepted")

            else -> utAuthenticated(route, path, request)
        }
    }

    private fun utAuthenticated(
        route: String,
        path: List<String>,
        request: RecordedRequest
    ): MockResponse {
        val id = path.getOrNull(1).orEmpty()
        val query = { name: String -> request.url.queryParameter(name) }
        return when (route) {
            "GET me" -> ok(Me.serializer(), Me(UserId(DEMO_USER_ID), "demo", Role.USER, KEY_ID))

            "GET keys" -> ok(ApiKeyList.serializer(), keys())

            "DELETE keys/*" -> MockResponse(code = 204)

            "POST tracks/*/request", "GET tracks/*/status" -> ok(
                TrackStatus.serializer(),
                ready(id)
            )

            "GET radio" -> radio(query("seed"), query("limit")?.toIntOrNull())

            "GET search" -> ok(SearchResult.serializer(), search(query("q").orEmpty()))

            "GET listen-now" -> ok(ListenNow.serializer(), listenNow())

            "GET imports" -> ok(
                ImportList.serializer(),
                ImportList(
                    imports.list(query("limit")?.toIntOrNull(), query("offset")?.toIntOrNull())
                )
            )

            "POST imports" -> createImport(request)

            "GET imports/*" -> imports.get(id)?.let { ok(Import.serializer(), it) }
                ?: problem(404, "not_found", "No such import in the demo")

            else -> problem(501, "not_implemented", "The demo does not do this")
        }
    }

    private fun serverInfo() = ServerInfo(
        name = "UltimateTunes Demo",
        version = "demo",
        apiVersion = "1",
        openSubsonic = OpenSubsonicInfo(
            SUBSONIC_VERSION,
            listOf("apiKeyAuthentication", "formPost", "songLyrics")
        ),
        capabilities = Capabilities(
            externalSearch = true,
            radio = true,
            lyrics = true,
            youtubeMusicImport = true,
            fileImport = true,
            streamingWhileDownloading = false
        )
    )

    private fun keys() = ApiKeyList(
        listOf(
            ApiKey(
                id = KEY_ID,
                name = "This phone (demo)",
                prefix = apiKey.take(KEY_PREFIX_LENGTH),
                createdAt = startedAt,
                lastUsedAt = clock.instant(),
                current = true
            )
        )
    )

    private fun ready(id: String) = TrackStatus(
        id = SongId(id),
        trackId = DemoCatalog.song(id)?.takeUnless { it.isExternal }?.id,
        state = TrackState.READY,
        progress = 1.0,
        attempts = 1,
        maxAttempts = 3,
        streamable = true,
        updatedAt = clock.instant()
    )

    private fun radio(seedId: String?, limit: Int?): MockResponse {
        val seed = seedId?.let(DemoCatalog::song)
            ?: return problem(404, "not_found", "No such song in the demo")
        val items = similarTo(seed, limit ?: RADIO_LENGTH).map { it.toTrackItem() }
        return ok(Radio.serializer(), Radio(seed.toTrackItem(), items))
    }

    /** Songs of the seed's genre first, then the rest, in a stable order per seed. */
    private fun similarTo(seed: Song, count: Int): List<Song> {
        val others = DemoCatalog.songs.filter { it.id != seed.id }
            .sortedBy { (it.id.value + seed.id.value).hashCode() }
        val (same, rest) = others.partition { it.genre == seed.genre }
        return (same + rest).take(count.coerceAtLeast(0))
    }

    private fun search(q: String): SearchResult {
        val needle = q.trim().lowercase()
        fun matches(text: String?) =
            needle.isNotEmpty() && text.orEmpty().lowercase().contains(needle)
        return SearchResult(
            query = q,
            artists = DemoCatalog.artists.filter { matches(it.name) }.map { it.toArtistItem() },
            albums = DemoCatalog.albums.filter { matches(it.name) || matches(it.artist) }
                .map { it.toAlbumItem() },
            tracks = (DemoCatalog.songs + DemoCatalog.externalSongs)
                .filter { matches(it.title) || matches(it.artist) || matches(it.album) }
                .take(SEARCH_LIMIT)
                .map { it.toTrackItem() }
        )
    }

    private fun listenNow() = ListenNow(
        recentlyPlayed = DemoCatalog.recentlyPlayed.map { it.toAlbumItem() },
        recentlyAdded = DemoCatalog.recentlyAdded.map { it.toAlbumItem() },
        mostPlayed = DemoCatalog.mostPlayed.map { it.toTrackItem() },
        favouriteRadios = DemoCatalog.stations
    )

    // ---- OpenSubsonic ----

    @Suppress("CyclomaticComplexMethod", "LongMethod") // A flat table of endpoints.
    private fun rest(endpoint: String, request: RecordedRequest): MockResponse {
        val params = paramsOf(request)
        fun param(name: String) = params[name]?.firstOrNull()
        fun all(name: String) = params[name].orEmpty()
        if (param("apiKey") != apiKey) return failure(44, "Invalid API key")
        val id = param("id").orEmpty()
        return when (endpoint) {
            "ping", "scrobble" -> envelope {}

            "getArtists" -> envelope {
                field("artists", ArtistIndexes.serializer(), artistIndexes())
            }

            "getArtist" -> DemoCatalog.artist(id)?.let { artist ->
                envelope { field("artist", Artist.serializer(), artist) }
            } ?: notFound()

            "getAlbum" -> DemoCatalog.album(id)?.let { album ->
                envelope { field("album", Album.serializer(), album.withStars()) }
            } ?: notFound()

            "getSong" -> DemoCatalog.song(id)?.let { song ->
                envelope { field("song", Song.serializer(), song.starredIfSo()) }
            } ?: notFound()

            "getAlbumList2" -> envelope {
                val albums = albumList(param("type"), param("genre"))
                    .drop(param("offset")?.toIntOrNull() ?: 0)
                    .take(param("size")?.toIntOrNull() ?: DEFAULT_LIST_SIZE)
                    .map { it.copy(song = emptyList()) }
                put("albumList2", buildJsonObject { field("album", ALBUMS, albums) })
            }

            "getRandomSongs" -> envelope {
                val songs = DemoCatalog.songs
                    .filter { param("genre") == null || it.genre == param("genre") }
                    .shuffled()
                    .take(param("size")?.toIntOrNull() ?: DEFAULT_LIST_SIZE)
                put("randomSongs", buildJsonObject { field("song", SONGS, songs) })
            }

            "getSimilarSongs2" -> DemoCatalog.song(id)?.let { seed ->
                envelope {
                    val songs = similarTo(seed, param("count")?.toIntOrNull() ?: RADIO_LENGTH)
                    put("similarSongs2", buildJsonObject { field("song", SONGS, songs) })
                }
            } ?: notFound()

            "getLyricsBySongId" -> DemoCatalog.song(id)?.let { song ->
                envelope {
                    put(
                        "lyricsList",
                        buildJsonObject {
                            field("structuredLyrics", LYRICS, listOf(DemoCatalog.lyrics(song)))
                        }
                    )
                }
            } ?: notFound()

            "getPlaylists" -> envelope {
                val list = synchronized(lock) { playlists.map { it.copy(entry = emptyList()) } }
                put("playlists", buildJsonObject { field("playlist", PLAYLISTS, list) })
            }

            "getPlaylist" -> synchronized(lock) { playlists.firstOrNull { it.id.value == id } }
                ?.let { envelope { field("playlist", Playlist.serializer(), it) } }
                ?: notFound()

            "createPlaylist" -> envelope {
                val created = createPlaylist(param("name") ?: "New Playlist", all("songId"))
                field("playlist", Playlist.serializer(), created)
            }

            "updatePlaylist" -> {
                updatePlaylist(
                    param("playlistId").orEmpty(),
                    PlaylistChange(
                        name = param("name"),
                        comment = param("comment"),
                        add = all("songIdToAdd"),
                        remove = all("songIndexToRemove").mapNotNull(String::toIntOrNull).toSet()
                    )
                )
                envelope {}
            }

            "deletePlaylist" -> {
                synchronized(lock) { playlists.removeAll { it.id.value == id } }
                envelope {}
            }

            "star", "unstar" -> {
                synchronized(lock) {
                    if (endpoint ==
                        "star"
                    ) {
                        starredSongs += all("id")
                    } else {
                        starredSongs -= all("id").toSet()
                    }
                }
                envelope {}
            }

            "getStarred2" -> envelope { field("starred2", Starred.serializer(), starred()) }

            "getPlayQueue" -> envelope {
                synchronized(lock) {
                    playQueue
                }?.let { field("playQueue", PlayQueue.serializer(), it) }
            }

            "savePlayQueue" -> {
                savePlayQueue(all("id"), param("current"), param("position")?.toLongOrNull())
                envelope {}
            }

            "stream", "download" -> DemoCatalog.song(id)?.let { audio(it.duration) } ?: notFound()

            "getCoverArt" -> image(id, param("size")?.toIntOrNull())

            else -> failure(0, "The demo does not do this")
        }
    }

    private fun artistIndexes() = ArtistIndexes(
        ignoredArticles = "The Los",
        index = DemoCatalog.artists
            .groupBy { (it.sortName ?: it.name).first().uppercaseChar().toString() }
            .toSortedMap()
            .map { (letter, artists) ->
                ArtistIndex(letter, artists.map { it.copy(album = emptyList()) })
            }
    )

    private fun albumList(type: String?, genre: String?): List<Album> = when (type) {
        "newest" -> DemoCatalog.albums.sortedByDescending { it.created }

        "recent" -> DemoCatalog.recentlyPlayed

        "frequent", "highest" -> DemoCatalog.albums.sortedByDescending { album ->
            album.song.sumOf { it.playCount ?: 0 }
        }

        "alphabeticalByName" -> DemoCatalog.albums.sortedBy { it.name }

        "alphabeticalByArtist" -> DemoCatalog.albums.sortedBy { it.artist }

        "byGenre" -> DemoCatalog.albums.filter { it.genre == genre }

        "starred" -> DemoCatalog.albums.filter { album ->
            synchronized(lock) { album.song.any { it.id.value in starredSongs } }
        }

        else -> DemoCatalog.albums.shuffled()
    }

    private fun Song.starredIfSo(): Song =
        if (synchronized(lock) { id.value in starredSongs }) copy(starred = startedAt) else this

    private fun Album.withStars(): Album = copy(song = song.map { it.starredIfSo() })

    private fun starred(): Starred {
        val ids = synchronized(lock) { starredSongs.toSet() }
        val songs = DemoCatalog.songs.filter {
            it.id.value in ids
        }.map { it.copy(starred = startedAt) }
        return Starred(
            album = DemoCatalog.albums.filter { album -> album.song.any { it.id.value in ids } }
                .map { it.copy(song = emptyList(), starred = startedAt) },
            song = songs
        )
    }

    private fun createPlaylist(name: String, songIds: List<String>): Playlist = synchronized(lock) {
        val playlist = DemoPlaylists.of(
            id = PlaylistId(DemoPlaylists.newId(playlists.size + 1)),
            name = name,
            songs = songIds.mapNotNull(DemoCatalog::song),
            at = clock.instant()
        )
        playlists += playlist
        playlist
    }

    private class PlaylistChange(
        val name: String?,
        val comment: String?,
        val add: List<String>,
        val remove: Set<Int>
    )

    private fun updatePlaylist(id: String, change: PlaylistChange) = synchronized(lock) {
        val index = playlists.indexOfFirst { it.id.value == id }
        if (index >= 0) {
            val old = playlists[index]
            val kept = old.entry.filterIndexed { i, _ -> i !in change.remove }
            playlists[index] = DemoPlaylists.of(
                id = old.id,
                name = change.name ?: old.name,
                songs = kept + change.add.mapNotNull(DemoCatalog::song),
                at = clock.instant(),
                comment = change.comment ?: old.comment
            )
        }
    }

    /** `POST /ut/v1/imports`: a playlist URL (JSON) or an uploaded file (multipart). */
    private fun createImport(request: RecordedRequest): MockResponse {
        val text = request.body?.utf8().orEmpty()
        val multipart = request.headers["Content-Type"].orEmpty().startsWith("multipart/")
        val import = if (multipart) fileImport(text) else urlImport(text)
        return if (import == null) {
            problem(400, "invalid_parameter", "Not a playlist URL or a known file format")
        } else {
            MockResponse(
                code = 202,
                headers = headersOf(
                    "Content-Type",
                    "application/json",
                    "Location",
                    "/ut/v1/imports/${import.id.value}"
                ),
                body = json.encodeToString(Import.serializer(), import)
            )
        }
    }

    private fun fileImport(text: String): Import? {
        val source = when (formField(text, "format")) {
            "csv" -> ImportSource.CSV
            "exportify_csv" -> ImportSource.EXPORTIFY_CSV
            "spotify_json" -> ImportSource.SPOTIFY_JSON
            else -> null
        }
        return source?.let { imports.create(it, null, formField(text, "name")) }
    }

    private fun urlImport(text: String): Import? {
        val body = runCatching { json.parseToJsonElement(text).jsonObject }.getOrNull()
        val url = body?.get("url")?.jsonPrimitive?.contentOrNull?.takeIf {
            it.startsWith("https://")
        }
        return url?.let {
            imports.create(ImportSource.YTMUSIC, it, body["name"]?.jsonPrimitive?.contentOrNull)
        }
    }

    private fun savePlayQueue(ids: List<String>, current: String?, position: Long?) =
        synchronized(lock) {
            playQueue = if (ids.isEmpty()) {
                null
            } else {
                PlayQueue(
                    current = current?.let(::SongId),
                    position = position,
                    username = "demo",
                    changed = clock.instant(),
                    changedBy = "UltimateTunes-Android",
                    entry = ids.mapNotNull(DemoCatalog::song)
                )
            }
        }

    private fun audio(seconds: Int?): MockResponse = MockResponse.Builder()
        .addHeader("Content-Type", DemoAudio.CONTENT_TYPE)
        .addHeader("Accept-Ranges", "none")
        .body(Buffer().write(DemoAudio.flac(seconds)))
        .build()

    private fun image(id: String, size: Int?): MockResponse {
        val label = DemoCatalog.coverLabels[id] ?: return notFound()
        return MockResponse.Builder()
            .addHeader("Content-Type", "image/png")
            .addHeader("Cache-Control", "max-age=86400")
            .body(Buffer().write(artwork(label, size)))
            .build()
    }

    // ---- plumbing ----

    private fun <T> JsonObjectBuilder.field(name: String, serializer: KSerializer<T>, value: T) {
        put(name, json.encodeToJsonElement(serializer, value))
    }

    private fun envelope(payload: JsonObjectBuilder.() -> Unit): MockResponse {
        val body = buildJsonObject {
            put(
                "subsonic-response",
                buildJsonObject {
                    put("status", "ok")
                    put("version", SUBSONIC_VERSION)
                    put("type", "UltimateTunes")
                    put("serverVersion", "demo")
                    put("openSubsonic", true)
                    payload()
                }
            )
        }
        return jsonResponse(200, body)
    }

    private fun failure(code: Int, message: String): MockResponse {
        val body = buildJsonObject {
            put(
                "subsonic-response",
                buildJsonObject {
                    put("status", "failed")
                    put("version", SUBSONIC_VERSION)
                    put("type", "UltimateTunes")
                    put("serverVersion", "demo")
                    put("openSubsonic", true)
                    put(
                        "error",
                        buildJsonObject {
                            put("code", code)
                            put("message", message)
                        }
                    )
                }
            )
        }
        return jsonResponse(200, body)
    }

    private fun notFound() = failure(70, "Not found in the demo")

    private fun <T> ok(serializer: KSerializer<T>, value: T): MockResponse =
        jsonResponse(200, json.encodeToJsonElement(serializer, value))

    private fun problem(status: Int, code: String, detail: String): MockResponse {
        val body = buildJsonObject {
            put("title", detail)
            put("status", status)
            put("detail", detail)
            put("code", code)
        }
        return MockResponse(
            code = status,
            headers = headersOf("Content-Type", "application/problem+json"),
            body = body.toString()
        )
    }

    private fun jsonResponse(code: Int, body: JsonElement) = MockResponse(
        code = code,
        headers = headersOf("Content-Type", "application/json"),
        body = body.toString()
    )

    private companion object {
        const val SUBSONIC_VERSION = "1.16.1"
        const val DEMO_USER_ID = "0199e0de-0000-7000-8000-000000000001"
        const val KEY_PREFIX_LENGTH = 12
        const val RADIO_LENGTH = 25
        const val SEARCH_LIMIT = 20
        const val DEFAULT_LIST_SIZE = 10
        val KEY_ID = ApiKeyId("0199e0de-0000-7000-8000-000000000002")
        val ALBUMS = ListSerializer(Album.serializer())
        val SONGS = ListSerializer(Song.serializer())
        val PLAYLISTS = ListSerializer(Playlist.serializer())
        val LYRICS = ListSerializer(Lyrics.serializer())

        /** The value of the multipart field [name] (for a file part, its content), or null. */
        fun formField(body: String, name: String): String? {
            val part = Regex(
                "Content-Disposition: form-data; name=\"$name\"[^\r\n]*\r\n(?:[^\r\n]+\r\n)*\r\n"
            )
            val start = part.find(body)?.range?.last?.plus(1) ?: return null
            val end = body.indexOf("\r\n--", start)
            return if (end < 0) null else body.substring(start, end)
        }

        /** Query parameters plus a `formPost` body. */
        fun paramsOf(request: RecordedRequest): Map<String, List<String>> {
            val all = mutableMapOf<String, MutableList<String>>()
            request.url.queryParameterNames.forEach { name ->
                all.getOrPut(name) { mutableListOf() } +=
                    request.url.queryParameterValues(name).filterNotNull()
            }
            if (request.headers["Content-Type"].orEmpty().startsWith(
                    "application/x-www-form-urlencoded"
                )
            ) {
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
