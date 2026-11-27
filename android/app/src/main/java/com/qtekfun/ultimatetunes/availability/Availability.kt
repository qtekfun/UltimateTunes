// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.availability

import androidx.compose.runtime.Immutable
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.ArtistId
import com.qtekfun.ultimatetunes.core.api.model.PlaylistId
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.ui.model.TrackTile

/**
 * What can be played now (RF-12). With no connection, what is not on the phone is shown dimmed;
 * in offline mode it is not shown at all. [songs] are the ids fully on the phone, [aliases] the
 * `yt:` ids kept under the library id they got; [albums], [artists] and [playlists] are those
 * with at least one song on the phone.
 */
@Immutable
data class Availability(
    val online: Boolean = true,
    val offlineMode: Boolean = false,
    val songs: Set<SongId> = emptySet(),
    val aliases: Map<SongId, SongId> = emptyMap(),
    val albums: Set<AlbumId> = emptySet(),
    val artists: Set<ArtistId> = emptySet(),
    val playlists: Set<PlaylistId> = emptySet()
) {
    /** Only what is on the phone can play: no connection, or offline mode. */
    val onlyPhone: Boolean get() = offlineMode || !online

    /** The id [id] plays under from the phone, or null when it is not on it. */
    fun phoneId(id: SongId): SongId? = phoneIdIn(songs, aliases, id)

    fun canPlay(id: SongId): Boolean = !onlyPhone || phoneId(id) != null

    fun canPlayAlbum(id: AlbumId): Boolean = !onlyPhone || id in albums

    fun canPlayArtist(id: ArtistId): Boolean = !onlyPhone || id in artists

    fun canPlayPlaylist(id: PlaylistId): Boolean = !onlyPhone || id in playlists

    fun shows(id: SongId): Boolean = !offlineMode || phoneId(id) != null

    fun showsAlbum(id: AlbumId): Boolean = !offlineMode || id in albums

    fun showsArtist(id: ArtistId): Boolean = !offlineMode || id in artists

    fun showsPlaylist(id: PlaylistId): Boolean = !offlineMode || id in playlists

    /**
     * The songs of [tracks] that can be queued now, under the ids they play under: from the
     * phone, a `yt:` song is its downloaded library file.
     */
    fun playable(tracks: List<TrackTile>): List<TrackTile> = if (!onlyPhone) {
        tracks
    } else {
        tracks.mapNotNull { track ->
            phoneId(track.id)?.let { id ->
                if (id == track.id) track else track.copy(id = id, isExternal = false)
            }
        }
    }
}

/** [id] if it is in [songs], else the id it was kept under, if that one is. */
internal fun phoneIdIn(songs: Set<SongId>, aliases: Map<SongId, SongId>, id: SongId): SongId? =
    id.takeIf { it in songs } ?: aliases[id]?.takeIf { it in songs }
