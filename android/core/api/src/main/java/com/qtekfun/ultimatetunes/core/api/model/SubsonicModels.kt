// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api.model

import kotlinx.serialization.Serializable

/*
 * Models of the OpenSubsonic subset (contracts/openapi/opensubsonic-subset.yaml), JSON form only:
 * the app always asks for `f=json`. Only the fields the app uses are declared; the others are
 * ignored. Names follow the app's vocabulary (Song, Album, Artist) rather than Subsonic's
 * (Child, AlbumID3, ArtistID3).
 */

/** ReplayGain in dB (gains) and linear peaks; empty for external or not yet analysed songs. */
@Serializable
data class ReplayGain(
    val trackGain: Double? = null,
    val albumGain: Double? = null,
    val trackPeak: Double? = null,
    val albumPeak: Double? = null,
    val baseGain: Double? = null
)

@Serializable
data class Genre(val name: String)

/** A minimal artist reference inside songs and albums. */
@Serializable
data class ArtistRef(val id: ArtistId, val name: String)

/** A song (`Child`). External songs have a `yt:` [id] and no file fields. */
@Serializable
data class Song(
    val id: SongId,
    val title: String,
    val parent: String? = null,
    val album: String? = null,
    val artist: String? = null,
    val track: Int? = null,
    val year: Int? = null,
    val genre: String? = null,
    val coverArt: CoverArtId? = null,
    val size: Long? = null,
    val contentType: String? = null,
    val suffix: String? = null,
    /** Seconds. */
    val duration: Int? = null,
    /** kbps. */
    val bitRate: Int? = null,
    val samplingRate: Int? = null,
    val channelCount: Int? = null,
    val playCount: Long? = null,
    val discNumber: Int? = null,
    val created: Timestamp? = null,
    val starred: Timestamp? = null,
    val played: Timestamp? = null,
    val albumId: AlbumId? = null,
    val artistId: ArtistId? = null,
    val musicBrainzId: String? = null,
    val genres: List<Genre> = emptyList(),
    val artists: List<ArtistRef> = emptyList(),
    val displayArtist: String? = null,
    val albumArtists: List<ArtistRef> = emptyList(),
    val displayAlbumArtist: String? = null,
    val replayGain: ReplayGain? = null
) {
    /** True for a YouTube Music song not archived in the library yet. */
    val isExternal: Boolean get() = id.isExternal
}

/** An album (`AlbumID3`); [song] is filled only by `getAlbum`. */
@Serializable
data class Album(
    val id: AlbumId,
    val name: String,
    val artist: String? = null,
    val artistId: ArtistId? = null,
    val coverArt: CoverArtId? = null,
    val songCount: Int = 0,
    /** Seconds. */
    val duration: Int = 0,
    val playCount: Long? = null,
    val created: Timestamp? = null,
    val starred: Timestamp? = null,
    val played: Timestamp? = null,
    val year: Int? = null,
    val genre: String? = null,
    val musicBrainzId: String? = null,
    val genres: List<Genre> = emptyList(),
    val artists: List<ArtistRef> = emptyList(),
    val displayArtist: String? = null,
    val song: List<Song> = emptyList()
) {
    val isExternal: Boolean get() = id.isExternal
}

/** An artist (`ArtistID3`); [album] is filled only by `getArtist`. */
@Serializable
data class Artist(
    val id: ArtistId,
    val name: String,
    val coverArt: CoverArtId? = null,
    val artistImageUrl: String? = null,
    val albumCount: Int? = null,
    val starred: Timestamp? = null,
    val musicBrainzId: String? = null,
    val sortName: String? = null,
    val album: List<Album> = emptyList()
) {
    val isExternal: Boolean get() = id.isExternal
}

/** One letter of the artist index. */
@Serializable
data class ArtistIndex(val name: String, val artist: List<Artist> = emptyList())

/** `getArtists`. */
@Serializable
data class ArtistIndexes(
    val ignoredArticles: String? = null,
    val index: List<ArtistIndex> = emptyList()
)

@Serializable
internal data class AlbumList2(val album: List<Album> = emptyList())

/** `search3`: only the songs are read (the library listing of an empty query). */
@Serializable
internal data class SearchResult3(val song: List<Song> = emptyList())

@Serializable
internal data class SongList(val song: List<Song> = emptyList())

/** One lyrics line; [start] in milliseconds, null for unsynced lyrics. */
@Serializable
data class LyricLine(val value: String, val start: Double? = null) {
    val startMillis: Long? get() = start?.toLong()
}

/** Lyrics of a song (`StructuredLyrics`), synced first. */
@Serializable
data class Lyrics(
    val lang: String,
    val synced: Boolean,
    val line: List<LyricLine> = emptyList(),
    val displayArtist: String? = null,
    val displayTitle: String? = null,
    /** Milliseconds. */
    val offset: Double? = null
)

@Serializable
internal data class LyricsList(val structuredLyrics: List<Lyrics> = emptyList())

/** A playlist; [entry] is filled only by `getPlaylist` and `createPlaylist`. */
@Serializable
data class Playlist(
    val id: PlaylistId,
    val name: String,
    val comment: String? = null,
    val owner: String? = null,
    val public: Boolean? = null,
    val songCount: Int = 0,
    /** Seconds. */
    val duration: Int = 0,
    val created: Timestamp? = null,
    val changed: Timestamp? = null,
    val coverArt: CoverArtId? = null,
    val readonly: Boolean? = null,
    val entry: List<Song> = emptyList()
)

@Serializable
internal data class Playlists(val playlist: List<Playlist> = emptyList())

/** `getStarred2`: the user's favourites. */
@Serializable
data class Starred(
    val artist: List<Artist> = emptyList(),
    val album: List<Album> = emptyList(),
    val song: List<Song> = emptyList()
)

/** The play queue saved across devices; [position] in milliseconds. */
@Serializable
data class PlayQueue(
    val current: SongId? = null,
    val position: Long? = null,
    val username: String,
    val changed: Timestamp,
    val changedBy: String,
    val entry: List<Song> = emptyList()
)

/** `getAlbumList2` list types. */
enum class AlbumListType(val wireName: String) {
    RANDOM("random"),
    NEWEST("newest"),
    HIGHEST("highest"),
    FREQUENT("frequent"),
    RECENT("recent"),
    ALPHABETICAL_BY_NAME("alphabeticalByName"),
    ALPHABETICAL_BY_ARTIST("alphabeticalByArtist"),
    STARRED("starred"),
    BY_YEAR("byYear"),
    BY_GENRE("byGenre")
}

/** The `error` of a failed `subsonic-response`. */
@Serializable
internal data class SubsonicError(
    val code: Int,
    val message: String? = null,
    val helpUrl: String? = null
)

/** The common part of every `subsonic-response`. */
@Serializable
internal data class SubsonicStatus(
    val status: String,
    val error: SubsonicError? = null,
    val serverVersion: String? = null
)
