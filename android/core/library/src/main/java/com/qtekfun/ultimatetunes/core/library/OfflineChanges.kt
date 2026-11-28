// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.library

import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.Playlist
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.api.model.Song
import com.qtekfun.ultimatetunes.core.api.model.SongId
import java.time.Instant
import kotlinx.coroutines.flow.Flow

/** What waits to be sent to the server. */
data class PendingStatus(
    /** Changes waiting. */
    val count: Int = 0,
    /** The number of the newest one: it grows with each change made. */
    val latest: Long = 0,
    /** Playlists with changes waiting: the catalog knows them better than the server. */
    val playlists: Set<PlaylistId> = emptySet(),
    /** Albums starred (true) or unstarred and not sent yet. */
    val albumFavourites: Map<AlbumId, Boolean> = emptyMap()
)

/** Something the user has to be told about a change that could not be sent. */
data class ChangeNotice(
    val id: Long,
    /** The playlist it was about; null for a favourite or a play. */
    val playlist: String?,
    /** The playlist is no longer on the server; false when the server refused the change. */
    val deletedOnServer: Boolean,
    /** Songs the server would not add, the rest of the change being made; 0 for a dropped one. */
    val skippedSongs: Int = 0
)

/** What one round of sending did. */
data class SendResult(
    /** Playlists or favourites reached the server or were dropped: the catalog should sync. */
    val changed: Boolean = false,
    /** Changes are still waiting. */
    val waiting: Boolean = false
)

/** True for a playlist made on this phone that the server does not know yet. */
val PlaylistId.isLocal: Boolean get() = value.startsWith(LOCAL_PLAYLIST_PREFIX)

internal const val LOCAL_PLAYLIST_PREFIX = "local:"

/**
 * Changes to playlists, favourites and plays. Each one shows in the catalog at once, with or
 * without a connection, and waits in a queue (kept across restarts) until [send] gets it to the
 * server. Each returns false (or null) when it could not be stored: the catalog is not this
 * connection's, or the phone cannot write.
 */
@Suppress("TooManyFunctions") // One function per change.
interface OfflineChanges {
    val status: Flow<PendingStatus>

    /** Oldest first; each stays until [dismiss]. */
    val notices: Flow<List<ChangeNotice>>

    /** The server ids that playlists made on the phone ended up with. */
    val replaced: Flow<Map<PlaylistId, PlaylistId>>

    /** The new playlist's temporary id (see [isLocal] and [replaced]). */
    suspend fun createPlaylist(name: String, songs: List<Song> = emptyList()): PlaylistId?

    suspend fun renamePlaylist(playlist: Playlist, name: String): Boolean

    suspend fun deletePlaylist(playlist: Playlist): Boolean

    /** [playlist] with its songs as the user sees them. */
    suspend fun addToPlaylist(playlist: Playlist, songs: List<Song>): Boolean

    /** Removes the song [playlist] shows at [index]. */
    suspend fun removeFromPlaylist(playlist: Playlist, index: Int): Boolean

    /** Puts the songs of [playlist] in [order]. */
    suspend fun reorderPlaylist(playlist: Playlist, order: List<SongId>): Boolean

    suspend fun setSongFavourite(song: Song, favourite: Boolean): Boolean

    suspend fun setAlbumFavourite(id: AlbumId, favourite: Boolean): Boolean

    /** A song played at [playedAt]. */
    suspend fun scrobble(id: SongId, playedAt: Instant): Boolean

    /** Sends what waits, oldest first. Also done by every catalog sync. */
    suspend fun send(): SendResult

    suspend fun dismiss(notice: Long)
}
