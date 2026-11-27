// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library

import androidx.room3.Room
import androidx.sqlite.driver.bundled.BundledSQLiteDriver
import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.TunesApiFactory
import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.core.api.model.Album
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.Artist
import com.qtekfun.ultimatetunes.core.api.model.ArtistId
import com.qtekfun.ultimatetunes.core.api.model.ArtistRef
import com.qtekfun.ultimatetunes.core.api.model.Playlist
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.api.model.Song
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.api.model.Starred
import com.qtekfun.ultimatetunes.core.library.db.CatalogDatabase
import java.time.Clock
import java.time.Duration
import java.time.Instant
import java.time.ZoneId
import java.time.ZoneOffset
import java.util.concurrent.CopyOnWriteArrayList
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import mockwebserver3.MockResponse
import mockwebserver3.RecordedRequest
import okhttp3.Headers.Companion.headersOf

val NOW: Instant = Instant.parse("2026-11-27T10:00:00Z")

class TestClock(var now: Instant = NOW) : Clock() {
    override fun instant(): Instant = now

    override fun getZone(): ZoneId = ZoneOffset.UTC

    override fun withZone(zone: ZoneId): Clock = this

    fun advance(by: Duration) {
        now += by
    }
}

fun artist(id: String, name: String) = ArtistRef(ArtistId(id), name)

@Suppress("LongParameterList")
fun song(
    id: String,
    title: String,
    album: String? = "al1",
    by: ArtistRef = artist("ar1", "Ñandú"),
    albumBy: ArtistRef = by,
    track: Int? = null,
    disc: Int? = null,
    year: Int? = 2020,
    created: Instant? = NOW,
    played: Instant? = null,
    plays: Long? = null
) = Song(
    id = SongId(id),
    title = title,
    albumId = album?.let(::AlbumId),
    album = album?.let { "Album $it" },
    artist = by.name,
    artistId = by.id,
    artists = listOf(by),
    displayArtist = by.name,
    albumArtists = listOf(albumBy),
    displayAlbumArtist = albumBy.name,
    track = track,
    discNumber = disc,
    year = year,
    duration = 100,
    created = created,
    played = played,
    playCount = plays
)

fun playlist(id: String, name: String, songs: List<Song>, changed: Instant = NOW) = Playlist(
    id = PlaylistId(id),
    name = name,
    songCount = songs.size,
    changed = changed,
    entry = songs
)

/**
 * The server's data, served through the overrides of the fake server. [failing] names endpoints
 * that answer 500; [onRequest] runs before an endpoint answers.
 */
class ServerLibrary(private val server: FakeTunesServer) {
    var user = "user-1"
    var songs = listOf<Song>()
    var playlists = listOf<Playlist>()
    var starred = Starred()
    val failing = mutableSetOf<String>()
    var onRequest: (String) -> Unit = {}

    /** Endpoints asked, in order (`getPlaylist:<id>`, `search3:<offset>`). */
    val asked = CopyOnWriteArrayList<String>()

    init {
        serve("ut/v1/me", "me") {
            JsonObject(
                mapOf(
                    "id" to JsonPrimitive(user),
                    "username" to JsonPrimitive("alice"),
                    "role" to JsonPrimitive("user")
                )
            )
        }
        serve("rest/search3", "search3", "songOffset") { request ->
            val offset = request.url.queryParameter("songOffset")!!.toInt()
            val count = request.url.queryParameter("songCount")!!.toInt()
            envelope("searchResult3" to wrap("song", songs.drop(offset).take(count).map(::json)))
        }
        serve("rest/getPlaylists", "getPlaylists") {
            val listed = playlists.map { json(it.copy(entry = emptyList())) }
            envelope("playlists" to wrap("playlist", listed))
        }
        serve("rest/getPlaylist", "getPlaylist", "id") { request ->
            val id = request.url.queryParameter("id")
            val found = playlists.firstOrNull { it.id.value == id }
            if (found == null) {
                failed(NOT_FOUND)
            } else {
                envelope("playlist" to Json.encodeToJsonElement(Playlist.serializer(), found))
            }
        }
        serve("rest/getStarred2", "getStarred2") {
            envelope("starred2" to Json.encodeToJsonElement(Starred.serializer(), starred))
        }
    }

    private fun json(song: Song) = Json.encodeToJsonElement(Song.serializer(), song)

    private fun json(playlist: Playlist) = Json.encodeToJsonElement(Playlist.serializer(), playlist)

    private fun wrap(name: String, items: List<JsonElement>) =
        JsonObject(mapOf(name to JsonArray(items)))

    private fun envelope(field: Pair<String, JsonElement>) = JsonObject(
        mapOf(
            "subsonic-response" to JsonObject(mapOf("status" to JsonPrimitive("ok"), field))
        )
    )

    private fun failed(code: Int) = JsonObject(
        mapOf(
            "subsonic-response" to JsonObject(
                mapOf(
                    "status" to JsonPrimitive("failed"),
                    "error" to JsonObject(mapOf("code" to JsonPrimitive(code)))
                )
            )
        )
    )

    private fun serve(
        path: String,
        name: String,
        parameter: String? = null,
        body: (RecordedRequest) -> JsonElement
    ) {
        server.dispatcher.override(path) { request ->
            val suffix = parameter?.let { ":" + request.url.queryParameter(it) }.orEmpty()
            asked += name + suffix
            onRequest(name)
            if (name in failing || name + suffix in failing) {
                MockResponse(code = 500)
            } else {
                MockResponse(
                    code = 200,
                    headers = headersOf("Content-Type", "application/json"),
                    body = body(request).toString()
                )
            }
        }
    }

    private companion object {
        const val NOT_FOUND = 70
    }
}

/** A syncer and repository over a fake server and a real SQLite in memory. */
class CatalogHarness(pageSize: Int = CatalogSyncer.PAGE_SIZE) : AutoCloseable {
    val server = FakeTunesServer().start()
    val remote = ServerLibrary(server)
    val config = InMemoryServerConfigSource(server.serverConfig())
    val clock = TestClock()
    val api = TunesApiFactory.create(TunesApiFactory.httpClient(config), config, clock)
    internal val database = Room.inMemoryDatabaseBuilder<CatalogDatabase>()
        .setDriver(BundledSQLiteDriver())
        .build()
    internal val syncer = CatalogSyncer(api, database, config, clock, pageSize = pageSize)
    val repository: LibraryRepository =
        DatabaseLibraryRepository(database.browse(), syncer.activity, config.config)

    override fun close() {
        database.close()
        server.close()
    }
}
