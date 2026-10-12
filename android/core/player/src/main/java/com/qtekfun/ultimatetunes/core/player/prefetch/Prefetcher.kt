// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.prefetch

import com.qtekfun.ultimatetunes.core.api.model.SongId
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

/** How the [Prefetcher] reaches the server and the cache. */
interface PrefetchTarget {
    /** True when the start of [id] is already on the phone (cached or downloaded). */
    fun isAvailable(id: SongId): Boolean

    /** Asks the server to download [id] now; false if the request failed. */
    suspend fun requestOnServer(id: SongId): Boolean

    /** Loads the first [bytes] of [id] into the cache; false if that failed. */
    suspend fun preload(id: SongId, bytes: Long): Boolean
}

/**
 * Runs the [PrefetchPlanner]'s actions in [scope] each time the queue moves. A snapshot with the
 * same upcoming songs as the running work leaves it alone (a timeline change that keeps the next
 * song must not restart its preload); a different one cancels it. Failed and cancelled actions are
 * forgotten at once, so the next snapshot plans them again.
 *
 * Not thread-safe: [scope] must run on the thread that calls it (the player's).
 */
class Prefetcher(
    private val planner: PrefetchPlanner,
    private val target: PrefetchTarget,
    private val scope: CoroutineScope
) {
    private var running: Job? = null
    private var pending = mutableListOf<PrefetchAction>()
    private var runningFor: Pair<List<SongId>, Boolean>? = null

    /** Plans for [snapshot] and starts the work; returns the newly planned actions. */
    fun onQueueChanged(snapshot: QueueSnapshot): List<PrefetchAction> {
        val targets = planner.targetsOf(snapshot) to snapshot.offlineOnly
        val job = running
        if (job != null && job.isActive && targets == runningFor) return emptyList()
        stop()
        val actions = planner.plan(snapshot, target::isAvailable)
        if (actions.isNotEmpty()) start(actions, targets)
        return actions
    }

    private fun start(actions: List<PrefetchAction>, targets: Pair<List<SongId>, Boolean>) {
        val left = actions.toMutableList()
        pending = left
        runningFor = targets
        running = scope.launch {
            for (action in actions) {
                val done = run(action)
                left.remove(action)
                if (!done) planner.forget(action)
            }
        }
    }

    /** Stops the running work. */
    fun cancel() = stop()

    private fun stop() {
        running?.cancel()
        running = null
        runningFor = null
        // Synchronously, so a new plan made right after sees them as not done.
        pending.forEach(planner::forget)
        pending = mutableListOf()
    }

    private suspend fun run(action: PrefetchAction): Boolean = when (action) {
        is PrefetchAction.RequestOnServer -> target.requestOnServer(action.id)
        is PrefetchAction.Preload -> target.preload(action.id, action.bytes)
    }
}
