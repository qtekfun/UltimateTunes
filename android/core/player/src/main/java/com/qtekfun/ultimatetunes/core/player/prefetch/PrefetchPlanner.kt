// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.prefetch

import com.qtekfun.ultimatetunes.core.api.model.SongId

/** Where the play queue stands, as the prefetch planner sees it. */
data class QueueSnapshot(
    /** The song playing now, if any. */
    val current: SongId?,
    /** The songs that will play next, in order (shuffle and repeat already applied). */
    val upcoming: List<SongId>,
    /** True when the user asked for cached and downloaded music only: no network at all. */
    val offlineOnly: Boolean = false
)

/** One thing to do ahead of time for an upcoming song. */
sealed interface PrefetchAction {
    val id: SongId

    /** `POST /ut/v1/tracks/{id}/request` with reason `prefetch`, so the server downloads it now. */
    data class RequestOnServer(override val id: SongId) : PrefetchAction

    /** Load the first [bytes] of the song into the cache, so it starts at once. */
    data class Preload(override val id: SongId, val bytes: Long) : PrefetchAction
}

/**
 * The queue prefetch planner (RF-12): the next [lookahead] songs are requested on the server, if
 * they are not in the library yet, and their first bytes are preloaded, unless they are already
 * cached or downloaded. Beyond the very next song only library songs are preloaded: a `yt:` song
 * further ahead is still downloading on the server, and the queue switches it to its library id
 * once archived (a raw start cached under its `yt:` key would be wasted). Each action is planned
 * once per song; [forget] lets a failed one be planned again.
 *
 * Not thread-safe: call it from one thread (the player's).
 */
class PrefetchPlanner(
    private val lookahead: Int = 1,
    private val preloadBytes: Long,
    private val memory: Int = DEFAULT_MEMORY
) {
    private val requested = LinkedHashSet<SongId>()
    private val preloaded = LinkedHashSet<SongId>()

    init {
        require(lookahead >= 1) { "lookahead must be at least 1" }
        require(preloadBytes > 0) { "preloadBytes must be positive" }
        require(memory >= lookahead) { "memory must hold the lookahead" }
    }

    /**
     * The actions for [snapshot], requests before preloads. [isAvailable] tells whether a song's
     * start is already on the phone (cached or downloaded).
     */
    fun plan(snapshot: QueueSnapshot, isAvailable: (SongId) -> Boolean): List<PrefetchAction> {
        if (snapshot.offlineOnly) return emptyList()
        val targets = targetsOf(snapshot)
        val requests = targets
            .filter { it.isExternal && remember(requested, it) }
            .map { PrefetchAction.RequestOnServer(it) }
        val preloads = targets
            .filterIndexed { index, id -> index == 0 || !id.isExternal }
            .filter { !isAvailable(it) && remember(preloaded, it) }
            .map { PrefetchAction.Preload(it, preloadBytes) }
        return requests + preloads
    }

    /** The upcoming songs [plan] looks at for [snapshot]: the next ones, without the current. */
    fun targetsOf(snapshot: QueueSnapshot): List<SongId> = snapshot.upcoming.asSequence()
        .filter { it != snapshot.current }
        .distinct()
        .take(lookahead)
        .toList()

    /** Lets [action] be planned again (it failed). */
    fun forget(action: PrefetchAction) {
        when (action) {
            is PrefetchAction.RequestOnServer -> requested.remove(action.id)
            is PrefetchAction.Preload -> preloaded.remove(action.id)
        }
    }

    /** Adds [id] to [seen], dropping the oldest beyond [memory]; false if it was there already. */
    private fun remember(seen: LinkedHashSet<SongId>, id: SongId): Boolean {
        if (!seen.add(id)) return false
        if (seen.size > memory) seen.remove(seen.first())
        return true
    }

    companion object {
        /** Upcoming songs the player prefetches (its [lookahead]) and follows until archived. */
        const val UPCOMING_SONGS = 3

        /** Songs remembered per action kind. */
        const val DEFAULT_MEMORY = 64
    }
}
