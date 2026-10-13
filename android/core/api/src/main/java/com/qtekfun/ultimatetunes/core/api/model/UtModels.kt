// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api.model

import java.time.Instant
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/*
 * Models of the UltimateTunes API (`/ut/v1`, contracts/openapi/ut-v1.yaml): camelCase JSON,
 * ISO 8601 UTC timestamps. Unknown properties are ignored, so the server can add fields.
 */

/** An ISO 8601 timestamp as [Instant]. */
typealias Timestamp =
    @Serializable(with = InstantSerializer::class)
    Instant

/** `GET /ut/v1/server`: what the Connect screen checks before asking for a key. */
@Serializable
data class ServerInfo(
    val name: String,
    val version: String,
    val apiVersion: String,
    val openSubsonic: OpenSubsonicInfo,
    val capabilities: Capabilities
)

@Serializable
data class OpenSubsonicInfo(val apiVersion: String, val extensions: List<String> = emptyList())

/** Feature flags: the app hides what is false. */
@Serializable
data class Capabilities(
    val externalSearch: Boolean,
    val radio: Boolean,
    val lyrics: Boolean,
    val youtubeMusicImport: Boolean,
    /** Playlist import from an uploaded file (CSV, Exportify CSV, Spotify data-export JSON). */
    val fileImport: Boolean,
    val streamingWhileDownloading: Boolean
)

@Serializable
enum class Role {
    @SerialName("admin")
    ADMIN,

    @SerialName("user")
    USER
}

/** `GET /ut/v1/me`. */
@Serializable
data class Me(val id: UserId, val username: String, val role: Role, val apiKeyId: ApiKeyId? = null)

/** An API key as listed (never the key itself). */
@Serializable
data class ApiKey(
    val id: ApiKeyId,
    val name: String,
    val prefix: String,
    val createdAt: Timestamp,
    val lastUsedAt: Timestamp? = null,
    val revokedAt: Timestamp? = null,
    val current: Boolean = false
)

@Serializable
data class ApiKeyList(val keys: List<ApiKey>)

/** Body of `POST /ut/v1/keys`. Its [toString] hides the password. */
@Serializable
internal data class CreateKeyRequest(val username: String, val password: String, val name: String) {
    override fun toString(): String =
        "CreateKeyRequest(username=$username, password=redacted, name=$name)"
}

/** `POST /ut/v1/keys`: the new key, whose [secret] is shown only this once. */
@Serializable
data class CreatedKey(val key: ApiKey, val secret: ApiKeySecret)

/** Job state of a track (RF-04). */
@Serializable
enum class TrackState {
    @SerialName("not_requested")
    NOT_REQUESTED,

    @SerialName("queued")
    QUEUED,

    @SerialName("downloading")
    DOWNLOADING,

    @SerialName("tagging")
    TAGGING,

    @SerialName("ready")
    READY,

    @SerialName("failed")
    FAILED,

    @SerialName("cancelled")
    CANCELLED;

    /** True while the server is still working on it (poll again). */
    val isInProgress: Boolean get() = this == QUEUED || this == DOWNLOADING || this == TAGGING
}

/** A job failure; [code] is one of the worker error codes of contracts/errors.md. */
@Serializable
data class TrackError(val code: String, val message: String)

/** `GET /ut/v1/tracks/{id}/status` and `POST /ut/v1/tracks/{id}/request`. */
@Serializable
data class TrackStatus(
    val id: SongId,
    val trackId: SongId? = null,
    val state: TrackState,
    val progress: Double,
    val attempts: Int,
    val maxAttempts: Int,
    val error: TrackError? = null,
    val streamable: Boolean,
    val updatedAt: Timestamp? = null
)

/** Why a track is requested: `prefetch` is the next song of the play queue. */
@Serializable
enum class RequestReason {
    @SerialName("keep")
    KEEP,

    @SerialName("prefetch")
    PREFETCH
}

@Serializable
internal data class RequestTrackBody(val reason: RequestReason)

/** State of the library track behind an item; null for external items never requested. */
@Serializable
enum class LibraryState {
    @SerialName("pending")
    PENDING,

    @SerialName("ready")
    READY,

    @SerialName("failed")
    FAILED
}

/** A song from the library or from YouTube Music ([isExternal]). */
@Serializable
data class TrackItem(
    val id: SongId,
    val title: String,
    val artist: String,
    val artistId: ArtistId? = null,
    val album: String? = null,
    val albumId: AlbumId? = null,
    val durationSec: Int? = null,
    val year: Int? = null,
    val coverArt: CoverArtId,
    val isExternal: Boolean,
    val libraryState: LibraryState? = null
)

@Serializable
data class AlbumItem(
    val id: AlbumId,
    val name: String,
    val artist: String,
    val artistId: ArtistId? = null,
    val year: Int? = null,
    val songCount: Int? = null,
    val coverArt: CoverArtId,
    val isExternal: Boolean
)

@Serializable
data class ArtistItem(
    val id: ArtistId,
    val name: String,
    val coverArt: CoverArtId,
    val isExternal: Boolean
)

/** `GET /ut/v1/radio`: the seed, then the queue (library items first-class, local-first). */
@Serializable
data class Radio(val seed: TrackItem, val items: List<TrackItem>)

/** `GET /ut/v1/search`: library results first, then external ones. */
@Serializable
data class SearchResult(
    val query: String,
    val artists: List<ArtistItem> = emptyList(),
    val albums: List<AlbumItem> = emptyList(),
    val tracks: List<TrackItem> = emptyList()
)

@Serializable
internal data class CreateImportBody(val url: String, val name: String? = null)

@Serializable
enum class ImportSource {
    @SerialName("ytmusic")
    YTMUSIC,

    @SerialName("csv")
    CSV,

    @SerialName("exportify_csv")
    EXPORTIFY_CSV,

    @SerialName("spotify_json")
    SPOTIFY_JSON
}

/**
 * The format of an uploaded playlist file (`POST /ut/v1/imports`, multipart):
 * - [CSV]: a header row with `title`, `artist` (several joined with `;`), optional `album`,
 *   `duration` (seconds or m:ss) and `isrc`;
 * - [EXPORTIFY_CSV]: the CSV Exportify writes;
 * - [SPOTIFY_JSON]: a playlist file of Spotify's "Download your data" export.
 */
enum class ImportFileFormat(val wireName: String, val mediaType: String) {
    CSV("csv", "text/csv"),
    EXPORTIFY_CSV("exportify_csv", "text/csv"),
    SPOTIFY_JSON("spotify_json", "application/json")
}

@Serializable
enum class ImportState {
    @SerialName("queued")
    QUEUED,

    @SerialName("reading")
    READING,

    @SerialName("matching")
    MATCHING,

    @SerialName("done")
    DONE,

    @SerialName("failed")
    FAILED
}

@Serializable
enum class ImportItemState {
    @SerialName("pending")
    PENDING,

    @SerialName("matched")
    MATCHED,

    @SerialName("not_found")
    NOT_FOUND,

    @SerialName("failed")
    FAILED
}

/** One source track of an import and what it matched. */
@Serializable
data class ImportItem(
    val position: Int,
    val sourceTitle: String,
    val sourceArtist: String? = null,
    val sourceAlbum: String? = null,
    val sourceDurationSec: Int? = null,
    val state: ImportItemState,
    val matchScore: Double? = null,
    val track: TrackItem? = null,
    val error: String? = null
)

/**
 * A playlist import. [items] (the match report) is filled by `GET /ut/v1/imports/{id}` and empty
 * in the list.
 */
@Serializable
data class Import(
    val id: ImportId,
    val source: ImportSource,
    /** The playlist URL of a `ytmusic` import; null for file imports. */
    val sourceUrl: String? = null,
    val name: String? = null,
    val state: ImportState,
    val total: Int,
    val matched: Int,
    val notFound: Int,
    val progress: Double,
    val playlistId: PlaylistId? = null,
    val error: TrackError? = null,
    val createdAt: Timestamp,
    val updatedAt: Timestamp,
    val finishedAt: Timestamp? = null,
    val items: List<ImportItem> = emptyList()
)

@Serializable
data class ImportList(val imports: List<Import>)

/** A radio shelf entry of Listen Now; pass [seedId] to the radio. */
@Serializable
data class RadioStation(
    val seedId: SongId,
    val title: String,
    val subtitle: String? = null,
    val coverArt: CoverArtId
)

/** `GET /ut/v1/listen-now`. */
@Serializable
data class ListenNow(
    val recentlyPlayed: List<AlbumItem> = emptyList(),
    val recentlyAdded: List<AlbumItem> = emptyList(),
    val mostPlayed: List<TrackItem> = emptyList(),
    val favouriteRadios: List<RadioStation> = emptyList()
)

/**
 * `GET /ut/v1/recommendations` (RF-11): new songs to discover, seeded from the caller's plays and
 * favourites, plus [shelves] from external sources the admin switched on. Empty when the caller has
 * no history and no external source is on.
 */
@Serializable
data class Recommendations(
    val recommendedForYou: List<TrackItem> = emptyList(),
    val becauseYouPlayed: List<RecommendationShelf> = emptyList(),
    val shelves: List<SourceShelf> = emptyList()
) {
    /** No songs to show in any shelf (empty history, nothing switched on). */
    val isEmpty: Boolean
        get() = recommendedForYou.isEmpty() &&
            becauseYouPlayed.all { it.items.isEmpty() } &&
            shelves.all { it.items.isEmpty() }
}

/** One "Because you played …" shelf: the [seed] song and the new songs its radio found. */
@Serializable
data class RecommendationShelf(val seed: TrackItem, val items: List<TrackItem> = emptyList())

/**
 * A shelf from an external recommendation source the admin switched on (e.g. ListenBrainz). [title]
 * is ready to show (e.g. "Popular on ListenBrainz · The Paper Lanterns"); [source] identifies the
 * origin (e.g. `listenbrainz`).
 */
@Serializable
data class SourceShelf(
    val source: String,
    val title: String,
    val items: List<TrackItem> = emptyList()
)

/** `GET /ut/v1/charts` (RF-11): a country's top chart songs, mapped local-first. */
@Serializable
data class Charts(val country: String, val items: List<TrackItem> = emptyList())

/** `GET /ut/v1/moods` (RF-11): the "Moods & genres" categories. */
@Serializable
data class Moods(val categories: List<MoodCategory> = emptyList())

/** One "Moods & genres" category; pass [id] to `GET /ut/v1/moods/{moodId}` for its songs. */
@Serializable
data class MoodCategory(val id: String, val title: String)

/** `GET /ut/v1/moods/{moodId}` (RF-11): the songs of one mood or genre category. */
@Serializable
data class MoodTracks(val id: String, val items: List<TrackItem> = emptyList())

/** RFC 9457 problem details of `/ut/v1` errors. Clients switch on [code] only. */
@Serializable
internal data class Problem(
    val type: String? = null,
    val title: String? = null,
    val status: Int? = null,
    val detail: String? = null,
    val instance: String? = null,
    val code: String,
    val retryAfter: Long? = null
)
