// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player

import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.Song
import com.qtekfun.ultimatetunes.core.api.model.SongId
import kotlinx.serialization.Serializable

/**
 * A song as the player and the offline downloads know it: enough to show it in the queue, the
 * notification and the Downloads list without asking the server. [artworkUrl] carries no
 * credentials (the image loader's OkHttp client adds them).
 */
@Serializable
data class PlayableTrack(
    val id: SongId,
    val title: String,
    val artist: String,
    val album: String? = null,
    val albumId: AlbumId? = null,
    val durationMs: Long? = null,
    val artworkUrl: String? = null,
    val trackNumber: Int? = null
) {
    /** True for a YouTube Music song not archived in the library yet. */
    val isExternal: Boolean get() = id.isExternal

    companion object {
        /** Artwork size asked for the notification and lists, in pixels. */
        const val ARTWORK_PX = 600

        private const val MS_PER_SECOND = 1000L

        /** [song] as a [PlayableTrack], its artwork URL from [api]. */
        fun of(song: Song, api: TunesApi): PlayableTrack = PlayableTrack(
            id = song.id,
            title = song.title,
            artist = song.displayArtist ?: song.artist.orEmpty(),
            album = song.album,
            albumId = song.albumId,
            durationMs = song.duration?.let { it * MS_PER_SECOND },
            artworkUrl = song.coverArt?.let { api.coverArtUrl(it, ARTWORK_PX)?.toString() },
            trackNumber = song.track
        )
    }
}
