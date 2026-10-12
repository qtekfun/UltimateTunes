// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.offline

import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.player.PlayableTrack

/** What one sync changes in the offline downloads. */
data class SyncPlan(
    /** Songs to download (always library ids). */
    val add: List<PlayableTrack>,
    /** Downloads nothing in the selection wants any more. */
    val remove: Set<SongId>,
    /** `yt:` songs still downloading on the server; the next sync picks them up. */
    val awaitingServer: List<SongId>,
    /** False while some album or playlist was never read: nothing is removed then. */
    val complete: Boolean
)

/**
 * Offline sync (RF-12): the downloads become exactly the songs of the selection. Songs added to a
 * kept playlist are downloaded; removed ones are freed, unless another kept item still has them.
 */
object OfflineSyncPlanner {
    /** The plan for [selection], given the songs [downloaded] already (or downloading). */
    fun plan(selection: OfflineSelection, downloaded: Set<SongId>): SyncPlan {
        val wanted = (selection.tracks + selection.collections.flatMap { it.members.orEmpty() })
            .distinctBy { it.id }
        val awaiting = mutableListOf<SongId>()
        val resolved = wanted.mapNotNull { track ->
            val libraryId = if (track.isExternal) selection.aliases[track.id] else track.id
            if (libraryId == null) awaiting += track.id
            libraryId?.let { track.copy(id = it) }
        }.distinctBy { it.id }
        val keep = resolved.mapTo(HashSet()) { it.id }
        val complete = selection.collections.all { it.members != null }
        return SyncPlan(
            add = resolved.filter { it.id !in downloaded },
            remove = if (complete) downloaded - keep else emptySet(),
            awaitingServer = awaiting,
            complete = complete
        )
    }
}
