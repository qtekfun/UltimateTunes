// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui

import com.qtekfun.ultimatetunes.core.api.ErrorKind
import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesError
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.Album
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.AlbumItem
import com.qtekfun.ultimatetunes.core.api.model.AlbumListType
import com.qtekfun.ultimatetunes.core.api.model.ApiKey
import com.qtekfun.ultimatetunes.core.api.model.ApiKeyId
import com.qtekfun.ultimatetunes.core.api.model.ApiKeyList
import com.qtekfun.ultimatetunes.core.api.model.ApiKeySecret
import com.qtekfun.ultimatetunes.core.api.model.Artist
import com.qtekfun.ultimatetunes.core.api.model.ArtistId
import com.qtekfun.ultimatetunes.core.api.model.ArtistIndex
import com.qtekfun.ultimatetunes.core.api.model.ArtistIndexes
import com.qtekfun.ultimatetunes.core.api.model.ArtistItem
import com.qtekfun.ultimatetunes.core.api.model.Capabilities
import com.qtekfun.ultimatetunes.core.api.model.Charts
import com.qtekfun.ultimatetunes.core.api.model.CoverArtId
import com.qtekfun.ultimatetunes.core.api.model.CreatedKey
import com.qtekfun.ultimatetunes.core.api.model.Import
import com.qtekfun.ultimatetunes.core.api.model.ImportFileFormat
import com.qtekfun.ultimatetunes.core.api.model.ImportId
import com.qtekfun.ultimatetunes.core.api.model.ImportItem
import com.qtekfun.ultimatetunes.core.api.model.ImportItemState
import com.qtekfun.ultimatetunes.core.api.model.ImportSource
import com.qtekfun.ultimatetunes.core.api.model.ImportState
import com.qtekfun.ultimatetunes.core.api.model.ListenNow
import com.qtekfun.ultimatetunes.core.api.model.LyricLine
import com.qtekfun.ultimatetunes.core.api.model.Lyrics
import com.qtekfun.ultimatetunes.core.api.model.Me
import com.qtekfun.ultimatetunes.core.api.model.MoodCategory
import com.qtekfun.ultimatetunes.core.api.model.MoodTracks
import com.qtekfun.ultimatetunes.core.api.model.Moods
import com.qtekfun.ultimatetunes.core.api.model.OpenSubsonicInfo
import com.qtekfun.ultimatetunes.core.api.model.PlayQueue
import com.qtekfun.ultimatetunes.core.api.model.Playlist
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.api.model.Radio
import com.qtekfun.ultimatetunes.core.api.model.RadioStation
import com.qtekfun.ultimatetunes.core.api.model.RecommendationShelf
import com.qtekfun.ultimatetunes.core.api.model.Recommendations
import com.qtekfun.ultimatetunes.core.api.model.RequestReason
import com.qtekfun.ultimatetunes.core.api.model.Role
import com.qtekfun.ultimatetunes.core.api.model.SearchResult
import com.qtekfun.ultimatetunes.core.api.model.ServerInfo
import com.qtekfun.ultimatetunes.core.api.model.Song
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.api.model.SourceShelf
import com.qtekfun.ultimatetunes.core.api.model.Starred
import com.qtekfun.ultimatetunes.core.api.model.TrackItem
import com.qtekfun.ultimatetunes.core.api.model.TrackStatus
import com.qtekfun.ultimatetunes.core.api.model.UserId
import java.time.Instant
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl

/**
 * An in-process [TunesApi] for UI tests on a device, with invented artists and songs (the same
 * ones as the contract examples). It never touches the network: covers have no URL and show
 * their placeholder. Playlists, favourites, revoked keys and imports change in memory; what the
 * screens do not use answers "not implemented".
 */
@Suppress("TooManyFunctions")
class FakeTunesApi(private val configSource: InMemoryServerConfigSource) : TunesApi {
    private fun <T> configured(value: () -> T): TunesResult<T> {
        val config = configSource.config.value ?: return TunesResult.NotConfigured
        return if (config.apiKey.value == API_KEY) {
            TunesResult.Success(value())
        } else {
            TunesResult.Unauthorized(TunesError(ErrorKind.INVALID_API_KEY), HTTP_UNAUTHORIZED)
        }
    }

    override suspend fun serverInfo(server: HttpUrl): TunesResult<ServerInfo> = TunesResult.Success(
        ServerInfo(
            name = "UltimateTunes",
            version = "0.1.0",
            apiVersion = "1",
            openSubsonic = OpenSubsonicInfo("1.16.1"),
            capabilities = Capabilities(
                externalSearch = true,
                radio = true,
                lyrics = true,
                youtubeMusicImport = true,
                fileImport = true,
                streamingWhileDownloading = true
            )
        )
    )

    override suspend fun me(): TunesResult<Me> =
        configured { Me(UserId("user-1"), "alice", Role.USER) }

    override suspend fun listenNow(): TunesResult<ListenNow> = configured {
        ListenNow(
            recentlyPlayed = listOf(HARBOUR, SALT),
            recentlyAdded = listOf(ORBIT, SALT, HARBOUR),
            mostPlayed = listOf(KEEPER, TIDEWATER, BRASAS),
            favouriteRadios = listOf(
                RadioStation(KEEPER.id, KEEPER_RADIO, "The Paper Lanterns", KEEPER.coverArt)
            )
        )
    }

    override suspend fun radio(seed: SongId, limit: Int?): TunesResult<Radio> = configured {
        val all = listOf(KEEPER, TIDEWATER, COPPER, BRASAS)
        val first = all.firstOrNull { it.id == seed } ?: KEEPER
        Radio(first, all - first)
    }

    override suspend fun recommendations(limit: Int?): TunesResult<Recommendations> = configured {
        Recommendations(
            recommendedForYou = listOf(COPPER, MOONS),
            becauseYouPlayed = listOf(
                RecommendationShelf(seed = KEEPER, items = listOf(COPPER, MOONS))
            ),
            shelves = listOf(
                SourceShelf(
                    source = "listenbrainz",
                    title = LISTENBRAINZ_SHELF,
                    items = listOf(MOONS)
                )
            )
        )
    }

    override suspend fun charts(country: String?, limit: Int?): TunesResult<Charts> = configured {
        Charts(country = country ?: "ZZ", items = listOf(KEEPER, TIDEWATER, COPPER))
    }

    override suspend fun moods(): TunesResult<Moods> = configured {
        Moods(listOf(MoodCategory("moods_chill", "Chill"), MoodCategory("moods_focus", "Focus")))
    }

    override suspend fun moodTracks(id: String, limit: Int?): TunesResult<MoodTracks> = configured {
        MoodTracks(id = id, items = listOf(KEEPER, TIDEWATER))
    }

    override suspend fun search(
        query: String,
        limit: Int?,
        external: Boolean
    ): TunesResult<SearchResult> = configured {
        SearchResult(
            query = query,
            artists = listOf(
                ArtistItem(LANTERNS_ID, "The Paper Lanterns", CoverArtId("ar-1"), false)
            ),
            albums = listOf(HARBOUR, DUSK),
            tracks = listOf(KEEPER, TIDEWATER, MOONS)
        )
    }

    override suspend fun album(id: AlbumId): TunesResult<Album> = configured {
        val item = listOf(HARBOUR, SALT, ORBIT, DUSK).firstOrNull { it.id == id } ?: HARBOUR
        val songs = listOf(KEEPER, TIDEWATER, BRASAS, COPPER, MOONS).filter {
            it.albumId == item.id
        }
        Album(
            id = item.id,
            name = item.name,
            artist = item.artist,
            artistId = LANTERNS_ID,
            year = 2023,
            genre = "Indie Pop",
            songCount = songs.size,
            duration = songs.sumOf { it.durationSec ?: 0 },
            starred = if (item.id in starredAlbums) Instant.EPOCH else null,
            song = songs.mapIndexed { i, t -> t.toSong(track = i + 1) }
        )
    }

    override suspend fun artist(id: ArtistId): TunesResult<Artist> = configured {
        Artist(id = LANTERNS_ID, name = "The Paper Lanterns", album = listOf(HARBOUR.toAlbum()))
    }

    override suspend fun artists(): TunesResult<ArtistIndexes> = configured {
        ArtistIndexes(
            index = listOf(
                ArtistIndex("M", listOf(Artist(ArtistId("artist-2"), "Marisol Vega"))),
                ArtistIndex("P", listOf(Artist(LANTERNS_ID, "The Paper Lanterns")))
            )
        )
    }

    override suspend fun albumList(
        type: AlbumListType,
        size: Int?,
        offset: Int?,
        fromYear: Int?,
        toYear: Int?,
        genre: String?
    ): TunesResult<List<Album>> = configured {
        if ((offset ?: 0) > 0) emptyList() else listOf(HARBOUR, SALT, ORBIT).map { it.toAlbum() }
    }

    override suspend fun lyrics(id: SongId): TunesResult<List<Lyrics>> = configured {
        listOf(
            Lyrics(
                lang = "und",
                synced = true,
                line = listOf(
                    LyricLine(LYRIC_FIRST, 0.0),
                    LyricLine("I keep the light for the ships that never were", 4210.0),
                    LyricLine("Turning and turning, the harbour asleep", 9875.0)
                )
            )
        )
    }

    override suspend fun playlists(): TunesResult<List<Playlist>> =
        configured { playlists.map { it.copy(entry = emptyList()) } }

    override suspend fun playlist(id: PlaylistId): TunesResult<Playlist> {
        val found = playlists.firstOrNull { it.id == id } ?: return notFound()
        return configured { found }
    }

    override suspend fun createPlaylist(
        name: String,
        songIds: List<SongId>
    ): TunesResult<Playlist> = configured {
        Playlist(PlaylistId("playlist-${playlists.size + 1}"), name).also { playlists += it }
    }

    override suspend fun updatePlaylist(
        id: PlaylistId,
        name: String?,
        comment: String?,
        public: Boolean?,
        songIdsToAdd: List<SongId>,
        songIndexesToRemove: List<Int>
    ): TunesResult<Unit> = configured {
        val i = playlists.indexOfFirst { it.id == id }
        if (i >= 0) {
            val p = playlists[i]
            val entries = p.entry.filterIndexed { index, _ -> index !in songIndexesToRemove } +
                songIdsToAdd.mapNotNull { added -> ALL_TRACKS.firstOrNull { it.id == added } }
                    .map { it.toSong() }
            playlists[i] = p.copy(name = name ?: p.name, entry = entries, songCount = entries.size)
        }
    }

    override suspend fun deletePlaylist(id: PlaylistId): TunesResult<Unit> =
        configured { playlists.removeAll { it.id == id } }

    override suspend fun star(
        songIds: List<SongId>,
        albumIds: List<AlbumId>,
        artistIds: List<ArtistId>
    ): TunesResult<Unit> = configured {
        starredAlbums += albumIds
        starredSongs += songIds
    }

    override suspend fun unstar(
        songIds: List<SongId>,
        albumIds: List<AlbumId>,
        artistIds: List<ArtistId>
    ): TunesResult<Unit> = configured {
        starredAlbums -= albumIds.toSet()
        starredSongs -= songIds.toSet()
    }

    override suspend fun starred(): TunesResult<Starred> = configured {
        Starred(
            album = listOf(HARBOUR, SALT, ORBIT, DUSK).filter { it.id in starredAlbums }
                .map { it.toAlbum() },
            song = listOf(KEEPER.toSong()) +
                ALL_TRACKS.filter { it.id in starredSongs && it != KEEPER }.map { it.toSong() }
        )
    }

    override suspend fun listKeys(): TunesResult<ApiKeyList> = configured {
        ApiKeyList(
            listOf(
                ApiKey(ApiKeyId("key-1"), "Phone", "utk_EXAMPLEe", Instant.EPOCH, current = true),
                ApiKey(ApiKeyId("key-2"), TABLET_KEY, "utk_EXAMPLEf", Instant.EPOCH)
            ).filter { it.id !in revokedKeys }
        )
    }

    override suspend fun revokeKey(id: ApiKeyId): TunesResult<Unit> = configured {
        revokedKeys += id
    }

    override suspend fun imports(limit: Int?, offset: Int?): TunesResult<List<Import>> =
        configured { imports.toList() }

    override suspend fun createImport(url: String, name: String?): TunesResult<Import> {
        if ("spotify" in
            url
        ) {
            return TunesResult.ApiError(TunesError(ErrorKind.UNSUPPORTED_URL), 400)
        }
        return configured { doneImport(name ?: IMPORTED_NAME).also { imports.add(0, it) } }
    }

    override suspend fun createFileImport(
        content: ByteArray,
        fileName: String,
        format: ImportFileFormat,
        name: String?
    ): TunesResult<Import> = configured { doneImport(name ?: fileName).also { imports.add(0, it) } }

    override suspend fun import(id: ImportId): TunesResult<Import> {
        val found = imports.firstOrNull { it.id == id } ?: return notFound()
        return configured { found }
    }

    override fun coverArtUrl(id: CoverArtId, size: Int?): HttpUrl? = null

    override fun streamUrl(id: SongId): HttpUrl? = null

    override fun downloadUrl(id: SongId): HttpUrl? = null

    // ---- In-memory state the screens change ----

    private val playlists = mutableListOf(
        Playlist(
            id = PlaylistId("playlist-1"),
            name = SUNDAY,
            songCount = 2,
            entry = listOf(KEEPER.toSong(), BRASAS.toSong())
        )
    )
    private val starredAlbums = mutableSetOf<AlbumId>()
    private val starredSongs = mutableSetOf<SongId>()

    /** What songs playlists got through `updatePlaylist` (UI tests read it). */
    fun playlistSongs(name: String): List<String> =
        playlists.firstOrNull { it.name == name }?.entry.orEmpty().map { it.title }

    /** Songs starred through the app. */
    val starredSongIds: Set<SongId> get() = starredSongs
    private val revokedKeys = mutableSetOf<ApiKeyId>()
    private val imports = mutableListOf<Import>()

    private fun doneImport(name: String) = Import(
        id = ImportId("import-${imports.size + 1}"),
        source = ImportSource.YTMUSIC,
        name = name,
        state = ImportState.DONE,
        total = 2,
        matched = 1,
        notFound = 1,
        progress = 1.0,
        playlistId = playlists.first().id,
        createdAt = Instant.EPOCH,
        updatedAt = Instant.EPOCH,
        items = listOf(
            ImportItem(
                0,
                KEEPER.title,
                KEEPER.artist,
                state = ImportItemState.MATCHED,
                track = KEEPER
            ),
            ImportItem(1, "Untitled Demo 4", "Northbound Static", state = ImportItemState.NOT_FOUND)
        )
    )

    private fun <T> notFound(): TunesResult<T> =
        TunesResult.ApiError(TunesError(ErrorKind.NOT_FOUND), HTTP_OK)

    // ---- Not used by the screens ----

    private fun <T> notImplemented(): TunesResult<T> =
        TunesResult.ApiError(TunesError(ErrorKind.NOT_IMPLEMENTED), HTTP_NOT_IMPLEMENTED)

    override suspend fun createKey(
        server: HttpUrl,
        username: String,
        password: String,
        deviceName: String
    ): TunesResult<CreatedKey> = notImplemented()

    override suspend fun requestTrack(id: SongId, reason: RequestReason): TunesResult<TrackStatus> =
        notImplemented()

    override suspend fun trackStatus(id: SongId): TunesResult<TrackStatus> = notImplemented()

    override suspend fun ping(): TunesResult<Unit> = notImplemented()

    override suspend fun song(id: SongId): TunesResult<Song> = notImplemented()

    override suspend fun randomSongs(size: Int?, genre: String?): TunesResult<List<Song>> =
        notImplemented()

    override suspend fun similarSongs(id: SongId, count: Int?): TunesResult<List<Song>> =
        notImplemented()

    override suspend fun scrobble(
        id: SongId,
        submission: Boolean,
        playedAt: Instant?
    ): TunesResult<Unit> = notImplemented()

    override suspend fun playQueue(): TunesResult<PlayQueue?> = notImplemented()

    override suspend fun savePlayQueue(
        ids: List<SongId>,
        current: SongId?,
        positionMillis: Long?
    ): TunesResult<Unit> = notImplemented()

    companion object {
        /** The key the fake accepts (the obviously fake example key of contracts/ids.md). */
        const val API_KEY = "utk_EXAMPLEexampleEXAMPLEexampleEXAMPLEexampleE"
        const val SERVER_URL = "https://music.example.net/"
        const val KEEPER_RADIO = "Lighthouse Keeper Radio"
        const val LISTENBRAINZ_SHELF = "Popular on ListenBrainz · The Paper Lanterns"
        const val SUNDAY = "Sunday Morning"
        const val TABLET_KEY = "Old tablet"
        const val IMPORTED_NAME = "Road Trip"
        const val LYRIC_FIRST = "Salt on the window, the night coming in"
        private const val HTTP_OK = 200
        val LANTERNS_ID = ArtistId("artist-1")

        private const val HTTP_UNAUTHORIZED = 401
        private const val HTTP_NOT_IMPLEMENTED = 501

        /** A configuration the fake accepts. */
        val config = ServerConfig(SERVER_URL.toHttpUrl(), ApiKeySecret(API_KEY))

        private fun album(n: Int, name: String, artist: String) = AlbumItem(
            id = AlbumId("album-$n"),
            name = name,
            artist = artist,
            coverArt = CoverArtId("al-album-$n"),
            isExternal = false
        )

        private fun track(
            id: String,
            title: String,
            artist: String,
            album: AlbumItem,
            external: Boolean = false
        ) = TrackItem(
            id = SongId(id),
            title = title,
            artist = artist,
            album = album.name,
            albumId = album.id,
            durationSec = 200,
            coverArt = album.coverArt,
            isExternal = external
        )

        val HARBOUR = album(1, "Harbour Lights", "The Paper Lanterns")
        private val SALT = album(2, "Salt & Ember", "Marisol Vega")
        private val ORBIT = album(3, "Low Orbit", "Northbound Static")
        val DUSK = AlbumItem(
            id = AlbumId("ytalbum:MPREb_k3Vd9QmT2xL"),
            name = "Lanterns at Dusk",
            artist = "The Paper Lanterns",
            coverArt = CoverArtId("ytalbum:MPREb_k3Vd9QmT2xL"),
            isExternal = true
        )
        val KEEPER = track("song-1", "Lighthouse Keeper", "The Paper Lanterns", HARBOUR)
        private val TIDEWATER = track("song-2", "Tidewater", "The Paper Lanterns", HARBOUR)
        private val BRASAS = track("song-3", "Brasas", "Marisol Vega", SALT)
        val COPPER = track("yt:Rb4Tn8wKx1c", "Copper Fields", "Marisol Vega", SALT, external = true)
        val MOONS =
            track(
                "yt:Qx7Lm2pZ0aB",
                "Paper Moons (Live)",
                "The Paper Lanterns",
                DUSK,
                external = true
            )

        private val ALL_TRACKS get() = listOf(KEEPER, TIDEWATER, BRASAS, COPPER, MOONS)

        private fun AlbumItem.toAlbum() = Album(
            id = id,
            name = name,
            artist = artist,
            artistId = LANTERNS_ID,
            coverArt = coverArt
        )

        private fun TrackItem.toSong(track: Int? = null) = Song(
            id = id,
            title = title,
            artist = artist,
            album = album,
            albumId = albumId,
            duration = durationSec,
            coverArt = coverArt,
            track = track
        )
    }
}
