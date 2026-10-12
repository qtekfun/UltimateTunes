// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

@file:OptIn(UnstableApi::class)

package com.qtekfun.ultimatetunes.core.player.media

import android.net.Uri
import android.os.Bundle
import androidx.annotation.OptIn
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.util.UnstableApi
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.player.PlayableTrack
import com.qtekfun.ultimatetunes.core.player.cache.CachePolicy

/**
 * [PlayableTrack] ⇄ Media3 [MediaItem]. A controller sends items **without** a URI (Media3 drops
 * it between controller and session anyway); the session resolves the URI from the media id with
 * [resolve], so a URI never comes from outside the app and never carries a key.
 */
object MediaItems {
    private const val EXTRA_ALBUM_ID = "ut.albumId"

    /** [track] as a media item for a controller: id and metadata, no URI. */
    fun of(track: PlayableTrack): MediaItem {
        val extras = Bundle().apply { track.albumId?.let { putString(EXTRA_ALBUM_ID, it.value) } }
        val metadata = MediaMetadata.Builder()
            .setTitle(track.title)
            .setArtist(track.artist)
            .setAlbumTitle(track.album)
            .setArtworkUri(track.artworkUrl?.let(Uri::parse))
            .setTrackNumber(track.trackNumber)
            .setDurationMs(track.durationMs)
            .setIsPlayable(true)
            .setIsBrowsable(false)
            .setMediaType(MediaMetadata.MEDIA_TYPE_MUSIC)
            .setExtras(extras)
            .build()
        return MediaItem.Builder().setMediaId(track.id.value).setMediaMetadata(metadata).build()
    }

    /** The song of [item]. */
    fun songOf(item: MediaItem): SongId = SongId(item.mediaId)

    /** The album of [item], when known. */
    fun albumOf(item: MediaItem): AlbumId? =
        item.mediaMetadata.extras?.getString(EXTRA_ALBUM_ID)?.let(::AlbumId)

    /** [item] back as a [PlayableTrack]. */
    fun trackOf(item: MediaItem): PlayableTrack {
        val metadata = item.mediaMetadata
        return PlayableTrack(
            id = songOf(item),
            title = metadata.title?.toString().orEmpty(),
            artist = metadata.artist?.toString().orEmpty(),
            album = metadata.albumTitle?.toString(),
            albumId = albumOf(item),
            durationMs = metadata.durationMs,
            artworkUrl = metadata.artworkUri?.toString(),
            trackNumber = metadata.trackNumber
        )
    }

    /** URI scheme of items resolved without a server: only offline downloads can play them. */
    const val OFFLINE_SCHEME = "ut-offline"

    /**
     * [item] ready to play: the `stream` URL of its id (no key; the OkHttp client adds it) and the
     * played id as cache key (CachePolicy). Without a configured server the URI is an
     * [OFFLINE_SCHEME] one that never reaches the network: a downloaded song still plays from the
     * downloads cache, anything else fails with a player error.
     */
    fun resolve(item: MediaItem, api: TunesApi): MediaItem {
        val id = songOf(item)
        val uri = api.streamUrl(id)?.toString() ?: "$OFFLINE_SCHEME:${Uri.encode(id.value)}"
        return item.buildUpon()
            .setUri(uri)
            .setCustomCacheKey(CachePolicy.cacheKey(id))
            .build()
    }

    /** [item] as library song [libraryId] (after the server archived it), resolved. */
    fun withId(item: MediaItem, libraryId: SongId, api: TunesApi): MediaItem =
        resolve(item.buildUpon().setMediaId(libraryId.value).build(), api)
}
