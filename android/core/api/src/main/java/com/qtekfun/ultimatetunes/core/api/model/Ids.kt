// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.api.model

import kotlinx.serialization.Serializable

/*
 * Ids of contracts/ids.md. Every id is an opaque string: it is sent back exactly as received and
 * never parsed, except for the prefix check that tells a YouTube Music item ("not in library yet")
 * from a library one. Wrapping them in value classes keeps a song id from being passed where an
 * album id is expected, at no runtime cost.
 */

/** Where an item lives: in the library (UUIDv7 id) or only on YouTube Music (virtual id). */
enum class IdOrigin { LIBRARY, YOUTUBE }

/** A song: a library UUID, or `yt:<videoId>` while it is not archived. */
@Serializable
@JvmInline
value class SongId(val value: String) {
    /** True for a `yt:` id: a YouTube Music song not archived in the library (yet). */
    val isExternal: Boolean get() = value.startsWith(SONG_PREFIX)

    val origin: IdOrigin get() = if (isExternal) IdOrigin.YOUTUBE else IdOrigin.LIBRARY

    /** The YouTube video id of a `yt:` id, or null for a library id. */
    val videoId: String? get() = if (isExternal) value.removePrefix(SONG_PREFIX) else null

    override fun toString(): String = value

    companion object {
        const val SONG_PREFIX = "yt:"
        private val VIDEO_ID = Regex("^[A-Za-z0-9_-]{11}$")

        /** The `yt:` id of [videoId], which must match `^[A-Za-z0-9_-]{11}$`. */
        fun ofVideo(videoId: String): SongId {
            require(VIDEO_ID.matches(videoId)) { "Not a YouTube video id" }
            return SongId(SONG_PREFIX + videoId)
        }
    }
}

/** An album: a library UUID, or `ytalbum:<browseId>`. */
@Serializable
@JvmInline
value class AlbumId(val value: String) {
    val isExternal: Boolean get() = value.startsWith(ALBUM_PREFIX)

    val origin: IdOrigin get() = if (isExternal) IdOrigin.YOUTUBE else IdOrigin.LIBRARY

    override fun toString(): String = value

    companion object {
        const val ALBUM_PREFIX = "ytalbum:"
    }
}

/** An artist: a library UUID, or `ytartist:<channelId>`. */
@Serializable
@JvmInline
value class ArtistId(val value: String) {
    val isExternal: Boolean get() = value.startsWith(ARTIST_PREFIX)

    val origin: IdOrigin get() = if (isExternal) IdOrigin.YOUTUBE else IdOrigin.LIBRARY

    override fun toString(): String = value

    companion object {
        const val ARTIST_PREFIX = "ytartist:"
    }
}

/** A cover art id for `getCoverArt` (`al-…`, `ar-…`, `pl-…`, `yt:…`, `ytalbum:…`, `ytartist:…`). */
@Serializable
@JvmInline
value class CoverArtId(val value: String) {
    override fun toString(): String = value
}

/** A user playlist (library UUID). */
@Serializable
@JvmInline
value class PlaylistId(val value: String) {
    override fun toString(): String = value
}

/** An API key's id (not the key itself). */
@Serializable
@JvmInline
value class ApiKeyId(val value: String) {
    override fun toString(): String = value
}

/** A playlist import. */
@Serializable
@JvmInline
value class ImportId(val value: String) {
    override fun toString(): String = value
}

/** A user. */
@Serializable
@JvmInline
value class UserId(val value: String) {
    override fun toString(): String = value
}
