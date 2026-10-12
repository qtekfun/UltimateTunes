// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api

import com.qtekfun.ultimatetunes.core.api.model.Album
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.AlbumListType
import com.qtekfun.ultimatetunes.core.api.model.ApiKeyId
import com.qtekfun.ultimatetunes.core.api.model.ApiKeyList
import com.qtekfun.ultimatetunes.core.api.model.Artist
import com.qtekfun.ultimatetunes.core.api.model.ArtistId
import com.qtekfun.ultimatetunes.core.api.model.ArtistIndexes
import com.qtekfun.ultimatetunes.core.api.model.CoverArtId
import com.qtekfun.ultimatetunes.core.api.model.CreatedKey
import com.qtekfun.ultimatetunes.core.api.model.Import
import com.qtekfun.ultimatetunes.core.api.model.ImportFileFormat
import com.qtekfun.ultimatetunes.core.api.model.ImportId
import com.qtekfun.ultimatetunes.core.api.model.ListenNow
import com.qtekfun.ultimatetunes.core.api.model.Lyrics
import com.qtekfun.ultimatetunes.core.api.model.Me
import com.qtekfun.ultimatetunes.core.api.model.PlayQueue
import com.qtekfun.ultimatetunes.core.api.model.Playlist
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.api.model.Radio
import com.qtekfun.ultimatetunes.core.api.model.RequestReason
import com.qtekfun.ultimatetunes.core.api.model.SearchResult
import com.qtekfun.ultimatetunes.core.api.model.ServerInfo
import com.qtekfun.ultimatetunes.core.api.model.Song
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.api.model.Starred
import com.qtekfun.ultimatetunes.core.api.model.TrackStatus
import java.time.Instant
import okhttp3.HttpUrl

/**
 * Everything the app asks the UltimateTunes server, over the `/ut/v1` API and the OpenSubsonic
 * subset (`/rest`, always JSON). The only way the UI reaches the network (CLAUDE.md).
 *
 * Every call reads the current [ServerConfig] and authenticates with its API key; without one it
 * returns [TunesResult.NotConfigured]. The two exceptions are [serverInfo] and [createKey], which
 * take the server URL explicitly because the Connect screen calls them before a key exists.
 */
@Suppress("TooManyFunctions") // One function per endpoint the app uses.
interface TunesApi {
    // ---- /ut/v1: connection and keys ----

    /** `GET /ut/v1/server` of [server] (no key needed): checks the URL on the Connect screen. */
    suspend fun serverInfo(server: HttpUrl): TunesResult<ServerInfo>

    /**
     * `POST /ut/v1/keys` on [server] with username and password: a new key for this device,
     * whose secret is returned only now.
     */
    suspend fun createKey(
        server: HttpUrl,
        username: String,
        password: String,
        deviceName: String
    ): TunesResult<CreatedKey>

    /** `GET /ut/v1/me`: also the check that a key works. */
    suspend fun me(): TunesResult<Me>

    /** `GET /ut/v1/keys`: this user's keys, newest first, revoked ones included. */
    suspend fun listKeys(): TunesResult<ApiKeyList>

    /** `DELETE /ut/v1/keys/{keyId}` (idempotent). */
    suspend fun revokeKey(id: ApiKeyId): TunesResult<Unit>

    // ---- /ut/v1: tracks, discovery, imports ----

    /** `POST /ut/v1/tracks/{id}/request`: keep a song in the library (or prefetch it). */
    suspend fun requestTrack(
        id: SongId,
        reason: RequestReason = RequestReason.KEEP
    ): TunesResult<TrackStatus>

    /** `GET /ut/v1/tracks/{id}/status`: download progress, and the library id once ready. */
    suspend fun trackStatus(id: SongId): TunesResult<TrackStatus>

    /** `GET /ut/v1/radio`: a radio queue from [seed], seed first. */
    suspend fun radio(seed: SongId, limit: Int? = null): TunesResult<Radio>

    /** `GET /ut/v1/search`: library and (unless [external] is false) YouTube Music results. */
    suspend fun search(
        query: String,
        limit: Int? = null,
        external: Boolean = true
    ): TunesResult<SearchResult>

    /** `GET /ut/v1/listen-now`: the Listen Now shelves. */
    suspend fun listenNow(): TunesResult<ListenNow>

    /** `GET /ut/v1/imports`: this user's imports, newest first, without items. */
    suspend fun imports(limit: Int? = null, offset: Int? = null): TunesResult<List<Import>>

    /** `POST /ut/v1/imports`: import a YouTube Music or YouTube playlist by URL. */
    suspend fun createImport(url: String, name: String? = null): TunesResult<Import>

    /**
     * `POST /ut/v1/imports` (multipart): import a playlist from an exported file. [content] is the
     * file (at most 1 MiB and 5000 rows, UTF-8; the server answers `payload_too_large` or
     * `invalid_parameter` otherwise), [fileName] its name, [name] the resulting playlist's name
     * (default: the name in the file, else the file name).
     */
    suspend fun createFileImport(
        content: ByteArray,
        fileName: String,
        format: ImportFileFormat,
        name: String? = null
    ): TunesResult<Import>

    /** `GET /ut/v1/imports/{id}`: progress and match report. */
    suspend fun import(id: ImportId): TunesResult<Import>

    // ---- OpenSubsonic: browsing ----

    /** `ping`: connectivity and credentials. */
    suspend fun ping(): TunesResult<Unit>

    /** `getArtists`: the artist index. */
    suspend fun artists(): TunesResult<ArtistIndexes>

    /** `getArtist`: an artist with its albums (`ytartist:` ids answered from YouTube Music). */
    suspend fun artist(id: ArtistId): TunesResult<Artist>

    /** `getAlbum`: an album with its songs (`ytalbum:` ids answered from YouTube Music). */
    suspend fun album(id: AlbumId): TunesResult<Album>

    /** `getSong`. */
    suspend fun song(id: SongId): TunesResult<Song>

    /** `getAlbumList2`. */
    suspend fun albumList(
        type: AlbumListType,
        size: Int? = null,
        offset: Int? = null,
        fromYear: Int? = null,
        toYear: Int? = null,
        genre: String? = null
    ): TunesResult<List<Album>>

    /** `getRandomSongs`. */
    suspend fun randomSongs(size: Int? = null, genre: String? = null): TunesResult<List<Song>>

    /** `getSimilarSongs2`: the radio behind OpenSubsonic. */
    suspend fun similarSongs(id: SongId, count: Int? = null): TunesResult<List<Song>>

    /** `getLyricsBySongId`: synced lyrics first; empty when none are known. */
    suspend fun lyrics(id: SongId): TunesResult<List<Lyrics>>

    // ---- OpenSubsonic: playlists ----

    /** `getPlaylists`. */
    suspend fun playlists(): TunesResult<List<Playlist>>

    /** `getPlaylist`: with its songs. */
    suspend fun playlist(id: PlaylistId): TunesResult<Playlist>

    /** `createPlaylist` with [name] and [songIds] (in order). */
    suspend fun createPlaylist(
        name: String,
        songIds: List<SongId> = emptyList()
    ): TunesResult<Playlist>

    /** `updatePlaylist`; only the given changes are sent. */
    @Suppress("LongParameterList") // Mirrors the endpoint's optional parameters.
    suspend fun updatePlaylist(
        id: PlaylistId,
        name: String? = null,
        comment: String? = null,
        public: Boolean? = null,
        songIdsToAdd: List<SongId> = emptyList(),
        songIndexesToRemove: List<Int> = emptyList()
    ): TunesResult<Unit>

    /** `deletePlaylist`. */
    suspend fun deletePlaylist(id: PlaylistId): TunesResult<Unit>

    // ---- OpenSubsonic: favourites, history, queue ----

    /** `star` songs, albums and artists. */
    suspend fun star(
        songIds: List<SongId> = emptyList(),
        albumIds: List<AlbumId> = emptyList(),
        artistIds: List<ArtistId> = emptyList()
    ): TunesResult<Unit>

    /** `unstar` songs, albums and artists. */
    suspend fun unstar(
        songIds: List<SongId> = emptyList(),
        albumIds: List<AlbumId> = emptyList(),
        artistIds: List<ArtistId> = emptyList()
    ): TunesResult<Unit>

    /** `getStarred2`: the favourites. */
    suspend fun starred(): TunesResult<Starred>

    /**
     * `scrobble`: [submission] true records a play at [playedAt] (now, from the injected clock,
     * when null); false only reports "now playing".
     */
    suspend fun scrobble(
        id: SongId,
        submission: Boolean = true,
        playedAt: Instant? = null
    ): TunesResult<Unit>

    /** `getPlayQueue`: the queue saved by any device; null when none was saved. */
    suspend fun playQueue(): TunesResult<PlayQueue?>

    /** `savePlayQueue` with [current] at [positionMillis]. An empty [ids] clears it. */
    suspend fun savePlayQueue(
        ids: List<SongId>,
        current: SongId? = null,
        positionMillis: Long? = null
    ): TunesResult<Unit>

    // ---- URLs for Media3 and the image loader ----

    /**
     * The `stream` URL of [id] (a `yt:` id streams while it downloads), or null when no server is
     * configured. It carries **no credentials**: load it with the `@TunesHttpClient` OkHttp client,
     * which adds them at send time, so the key never sits in Media3 cache keys, URIs or logs.
     */
    fun streamUrl(id: SongId): HttpUrl?

    /** The `download` URL of [id] (original file), without credentials like [streamUrl]. */
    fun downloadUrl(id: SongId): HttpUrl?

    /** The `getCoverArt` URL of [id], [size] pixels when given, without credentials. */
    fun coverArtUrl(id: CoverArtId, size: Int? = null): HttpUrl?
}
