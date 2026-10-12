// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.playback

import com.qtekfun.ultimatetunes.core.player.PlayableTrack
import com.qtekfun.ultimatetunes.ui.model.TrackTile

private const val MS_PER_SECOND = 1000L

/** [this] tile as the player's track. */
fun TrackTile.toPlayable(): PlayableTrack = PlayableTrack(
    id = id,
    title = title,
    artist = artist,
    album = album,
    albumId = albumId,
    durationMs = durationSec?.let { it * MS_PER_SECOND },
    artworkUrl = coverUrl,
    trackNumber = trackNumber
)

/** [this] track as a tile for the screens. */
fun PlayableTrack.toTile(): TrackTile = TrackTile(
    id = id,
    title = title,
    artist = artist,
    album = album,
    durationSec = durationMs?.let { (it / MS_PER_SECOND).toInt() },
    coverUrl = artworkUrl,
    isExternal = isExternal,
    albumId = albumId,
    trackNumber = trackNumber
)
