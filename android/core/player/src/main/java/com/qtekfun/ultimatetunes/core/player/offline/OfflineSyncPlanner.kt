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
    /**
     * False while some album, playlist or the library was never read: only dropped songs are
     * removed then.
     */
    val complete: Boolean
)

/**
 * Offline sync (RF-12): the downloads become exactly the songs of the selection. Songs added to a
 * kept playlist are downloaded; removed ones are freed, unless another kept item still has them.
 */
object OfflineSyncPlanner {
    /**
     * The plan for [selection], given every download the phone has ([downloaded], in any state)
     * and those of them that [failed] (downloaded again when still wanted, removed otherwise).
     * While some kept album or playlist was never read, only the [dropped] songs (the user just
     * let them go) are freed, if nothing known still wants them.
     */
    fun plan(
        selection: OfflineSelection,
        downloaded: Set<SongId>,
        failed: Set<SongId> = emptySet(),
        dropped: Set<SongId> = emptySet()
    ): SyncPlan {
        val wanted = (
            selection.tracks +
                selection.collections.flatMap { it.members.orEmpty() } +
                selection.library?.songs.orEmpty()
            ).distinctBy { it.id }
        val awaiting = mutableListOf<SongId>()
        val resolved = wanted.mapNotNull { track ->
            val libraryId = if (track.isExternal) selection.aliases[track.id] else track.id
            if (libraryId == null) awaiting += track.id
            libraryId?.let { track.copy(id = it) }
        }.distinctBy { it.id }
        val keep = resolved.mapTo(HashSet()) { it.id }
        val complete = selection.collections.all { it.members != null } &&
            (selection.library == null || selection.library.songs != null)
        val freeable = if (complete) downloaded else dropped.map { selection.aliases[it] ?: it }
        return SyncPlan(
            add = resolved.filter { it.id !in downloaded || it.id in failed },
            remove = freeable.filterTo(HashSet()) { it in downloaded && it !in keep },
            awaitingServer = awaiting,
            complete = complete
        )
    }
}
