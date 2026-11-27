// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.availability

import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.player.media.MediaCaches
import javax.inject.Inject

/** What the player's caches hold on the phone. */
interface CachedSongs {
    /** The library songs the play cache holds whole. Reads the disk: not on the main thread. */
    fun complete(): Set<SongId>

    /** Bytes of music on the phone: play cache and downloads. */
    fun usedBytes(): Long
}

/** [CachedSongs] of Media3's caches. */
class MediaCachedSongs @Inject constructor(private val caches: MediaCaches) : CachedSongs {
    override fun complete(): Set<SongId> = caches.completeLibrarySongs()

    override fun usedBytes(): Long = caches.usedBytes()
}
