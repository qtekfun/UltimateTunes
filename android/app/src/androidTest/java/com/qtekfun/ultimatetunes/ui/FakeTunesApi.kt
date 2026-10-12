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
import com.qtekfun.ultimatetunes.core.api.model.ApiKeyId
import com.qtekfun.ultimatetunes.core.api.model.ApiKeyList
import com.qtekfun.ultimatetunes.core.api.model.ApiKeySecret
import com.qtekfun.ultimatetunes.core.api.model.Artist
import com.qtekfun.ultimatetunes.core.api.model.ArtistId
import com.qtekfun.ultimatetunes.core.api.model.ArtistIndexes
import com.qtekfun.ultimatetunes.core.api.model.Capabilities
import com.qtekfun.ultimatetunes.core.api.model.CoverArtId
import com.qtekfun.ultimatetunes.core.api.model.CreatedKey
import com.qtekfun.ultimatetunes.core.api.model.Import
import com.qtekfun.ultimatetunes.core.api.model.ImportFileFormat
import com.qtekfun.ultimatetunes.core.api.model.ImportId
import com.qtekfun.ultimatetunes.core.api.model.ListenNow
import com.qtekfun.ultimatetunes.core.api.model.Lyrics
import com.qtekfun.ultimatetunes.core.api.model.Me
import com.qtekfun.ultimatetunes.core.api.model.OpenSubsonicInfo
import com.qtekfun.ultimatetunes.core.api.model.PlayQueue
import com.qtekfun.ultimatetunes.core.api.model.Playlist
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.api.model.Radio
import com.qtekfun.ultimatetunes.core.api.model.RadioStation
import com.qtekfun.ultimatetunes.core.api.model.RequestReason
import com.qtekfun.ultimatetunes.core.api.model.Role
import com.qtekfun.ultimatetunes.core.api.model.SearchResult
import com.qtekfun.ultimatetunes.core.api.model.ServerInfo
import com.qtekfun.ultimatetunes.core.api.model.Song
import com.qtekfun.ultimatetunes.core.api.model.SongId
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
 * their placeholder. What the T12 screens do not use answers "not implemented".
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

    override fun coverArtUrl(id: CoverArtId, size: Int?): HttpUrl? = null

    override fun streamUrl(id: SongId): HttpUrl? = null

    override fun downloadUrl(id: SongId): HttpUrl? = null

    // ---- Not used by the T12 screens ----

    private fun <T> notImplemented(): TunesResult<T> =
        TunesResult.ApiError(TunesError(ErrorKind.NOT_IMPLEMENTED), HTTP_NOT_IMPLEMENTED)

    override suspend fun createKey(
        server: HttpUrl,
        username: String,
        password: String,
        deviceName: String
    ): TunesResult<CreatedKey> = notImplemented()

    override suspend fun listKeys(): TunesResult<ApiKeyList> = notImplemented()

    override suspend fun revokeKey(id: ApiKeyId): TunesResult<Unit> = notImplemented()

    override suspend fun requestTrack(id: SongId, reason: RequestReason): TunesResult<TrackStatus> =
        notImplemented()

    override suspend fun trackStatus(id: SongId): TunesResult<TrackStatus> = notImplemented()

    override suspend fun search(
        query: String,
        limit: Int?,
        external: Boolean
    ): TunesResult<SearchResult> = notImplemented()

    override suspend fun imports(limit: Int?, offset: Int?): TunesResult<List<Import>> =
        notImplemented()

    override suspend fun createImport(url: String, name: String?): TunesResult<Import> =
        notImplemented()

    override suspend fun createFileImport(
        content: ByteArray,
        fileName: String,
        format: ImportFileFormat,
        name: String?
    ): TunesResult<Import> = notImplemented()

    override suspend fun import(id: ImportId): TunesResult<Import> = notImplemented()

    override suspend fun ping(): TunesResult<Unit> = notImplemented()

    override suspend fun artists(): TunesResult<ArtistIndexes> = notImplemented()

    override suspend fun artist(id: ArtistId): TunesResult<Artist> = notImplemented()

    override suspend fun album(id: AlbumId): TunesResult<Album> = notImplemented()

    override suspend fun song(id: SongId): TunesResult<Song> = notImplemented()

    override suspend fun albumList(
        type: AlbumListType,
        size: Int?,
        offset: Int?,
        fromYear: Int?,
        toYear: Int?,
        genre: String?
    ): TunesResult<List<Album>> = notImplemented()

    override suspend fun randomSongs(size: Int?, genre: String?): TunesResult<List<Song>> =
        notImplemented()

    override suspend fun similarSongs(id: SongId, count: Int?): TunesResult<List<Song>> =
        notImplemented()

    override suspend fun lyrics(id: SongId): TunesResult<List<Lyrics>> = notImplemented()

    override suspend fun playlists(): TunesResult<List<Playlist>> = notImplemented()

    override suspend fun playlist(id: PlaylistId): TunesResult<Playlist> = notImplemented()

    override suspend fun createPlaylist(
        name: String,
        songIds: List<SongId>
    ): TunesResult<Playlist> = notImplemented()

    override suspend fun updatePlaylist(
        id: PlaylistId,
        name: String?,
        comment: String?,
        public: Boolean?,
        songIdsToAdd: List<SongId>,
        songIndexesToRemove: List<Int>
    ): TunesResult<Unit> = notImplemented()

    override suspend fun deletePlaylist(id: PlaylistId): TunesResult<Unit> = notImplemented()

    override suspend fun star(
        songIds: List<SongId>,
        albumIds: List<AlbumId>,
        artistIds: List<ArtistId>
    ): TunesResult<Unit> = notImplemented()

    override suspend fun unstar(
        songIds: List<SongId>,
        albumIds: List<AlbumId>,
        artistIds: List<ArtistId>
    ): TunesResult<Unit> = notImplemented()

    override suspend fun starred(): TunesResult<Starred> = notImplemented()

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

        private val HARBOUR = album(1, "Harbour Lights", "The Paper Lanterns")
        private val SALT = album(2, "Salt & Ember", "Marisol Vega")
        private val ORBIT = album(3, "Low Orbit", "Northbound Static")
        val KEEPER = track("song-1", "Lighthouse Keeper", "The Paper Lanterns", HARBOUR)
        private val TIDEWATER = track("song-2", "Tidewater", "The Paper Lanterns", HARBOUR)
        private val BRASAS = track("song-3", "Brasas", "Marisol Vega", SALT)
        val COPPER = track("yt:Rb4Tn8wKx1c", "Copper Fields", "Marisol Vega", SALT, external = true)
    }
}
