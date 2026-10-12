// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.model

import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.AlbumItem
import com.qtekfun.ultimatetunes.core.api.model.CoverArtId
import com.qtekfun.ultimatetunes.core.api.model.RadioStation
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.api.model.TrackItem

/*
 * What the screens show, already shaped for Compose: plain immutable values with cover URLs
 * resolved through `TunesApi.coverArtUrl` (no credentials in them; the image loader's OkHttp
 * client adds the key at send time).
 */

/** Size in pixels asked for covers in grids and shelves. */
const val TILE_ARTWORK_PX = 600

/** An album in a grid or shelf. */
data class AlbumTile(
    val id: AlbumId,
    val title: String,
    val artist: String,
    val coverUrl: String?,
    val isExternal: Boolean
)

/** A song in a list, a shelf or the play queue. */
data class TrackTile(
    val id: SongId,
    val title: String,
    val artist: String,
    val album: String?,
    val durationSec: Int?,
    val coverUrl: String?,
    val isExternal: Boolean
)

/** A radio station, started from [seedId]. */
data class StationTile(
    val seedId: SongId,
    val title: String,
    val subtitle: String?,
    val coverUrl: String?
)

/** Why something could not be loaded, as the user can act on it. */
enum class LoadError {
    /** No connection to the server: check the network and retry. */
    NETWORK,

    /** The key was refused: connect again. */
    UNAUTHORIZED,

    /** No server configured. */
    NOT_CONFIGURED,

    /** The server answered with an error or something unexpected. */
    SERVER
}

/** The state of a screen that loads one thing. */
sealed interface LoadState<out T> {
    data object Loading : LoadState<Nothing>

    data class Ready<out T>(val value: T) : LoadState<T>

    data class Failed(val error: LoadError) : LoadState<Nothing>
}

/** The [LoadError] a failure is shown as. */
fun TunesResult.Failure.toLoadError(): LoadError = when (this) {
    is TunesResult.NetworkError -> LoadError.NETWORK
    is TunesResult.Unauthorized -> LoadError.UNAUTHORIZED
    TunesResult.NotConfigured -> LoadError.NOT_CONFIGURED
    is TunesResult.ApiError, is TunesResult.ProtocolError -> LoadError.SERVER
}

/** [result] as a [LoadState], its value transformed by [transform]. */
inline fun <T, R> loadStateOf(result: TunesResult<T>, transform: (T) -> R): LoadState<R> =
    when (result) {
        is TunesResult.Success -> LoadState.Ready(transform(result.value))
        is TunesResult.Failure -> LoadState.Failed(result.toLoadError())
    }

/** The cover URL of [id] at [size] pixels, or null when no server is configured. */
fun TunesApi.coverUrl(id: CoverArtId, size: Int = TILE_ARTWORK_PX): String? =
    coverArtUrl(id, size)?.toString()

fun AlbumItem.toTile(api: TunesApi): AlbumTile = AlbumTile(
    id = id,
    title = name,
    artist = artist,
    coverUrl = api.coverUrl(coverArt),
    isExternal = isExternal
)

fun TrackItem.toTile(api: TunesApi): TrackTile = TrackTile(
    id = id,
    title = title,
    artist = artist,
    album = album,
    durationSec = durationSec,
    coverUrl = api.coverUrl(coverArt),
    isExternal = isExternal
)

fun RadioStation.toTile(api: TunesApi): StationTile = StationTile(
    seedId = seedId,
    title = title,
    subtitle = subtitle,
    coverUrl = api.coverUrl(coverArt)
)
