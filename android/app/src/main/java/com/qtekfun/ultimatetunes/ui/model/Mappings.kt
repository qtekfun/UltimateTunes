// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.model

import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.model.Album
import com.qtekfun.ultimatetunes.core.api.model.Artist
import com.qtekfun.ultimatetunes.core.api.model.ArtistItem
import com.qtekfun.ultimatetunes.core.api.model.Playlist
import com.qtekfun.ultimatetunes.core.api.model.Song

/*
 * The browsing models of the API (search items and OpenSubsonic songs, albums, artists,
 * playlists) as tiles; covers resolved like in UiModels.kt.
 */

fun ArtistItem.toTile(api: TunesApi): ArtistTile = ArtistTile(
    id = id,
    name = name,
    coverUrl = api.coverUrl(coverArt),
    isExternal = isExternal
)

/** An OpenSubsonic song; [fallbackArtist] when the song has none (an album's own artist). */
fun Song.toTile(api: TunesApi, fallbackArtist: String = ""): TrackTile = TrackTile(
    id = id,
    title = title,
    artist = displayArtist ?: artist ?: fallbackArtist,
    album = album,
    durationSec = duration,
    coverUrl = coverArt?.let { api.coverUrl(it) },
    isExternal = isExternal,
    albumId = albumId,
    trackNumber = track,
    artistId = artistId ?: artists.firstOrNull()?.id,
    discNumber = discNumber,
    albumArtist = displayAlbumArtist ?: albumArtists.firstOrNull()?.name
)

fun Album.toTile(api: TunesApi): AlbumTile = AlbumTile(
    id = id,
    title = name,
    artist = displayArtist ?: artist.orEmpty(),
    coverUrl = coverArt?.let { api.coverUrl(it) },
    isExternal = isExternal
)

fun Artist.toTile(api: TunesApi): ArtistTile = ArtistTile(
    id = id,
    name = name,
    coverUrl = coverArt?.let { api.coverUrl(it) },
    isExternal = isExternal
)

fun Playlist.toTile(api: TunesApi): PlaylistTile = PlaylistTile(
    id = id,
    name = name,
    songCount = songCount,
    durationSec = duration,
    coverUrl = coverArt?.let { api.coverUrl(it) }
)
