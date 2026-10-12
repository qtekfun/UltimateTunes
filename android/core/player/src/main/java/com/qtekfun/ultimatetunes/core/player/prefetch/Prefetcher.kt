// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.prefetch

import com.qtekfun.ultimatetunes.core.api.model.SongId
import kotlinx.coroutines.CancellationException
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
 * Runs the [PrefetchPlanner]'s actions in [scope] each time the queue moves. A new snapshot
 * cancels the work still running for the previous one; failed or cancelled actions are
 * forgotten, so the next snapshot plans them again.
 */
class Prefetcher(
    private val planner: PrefetchPlanner,
    private val target: PrefetchTarget,
    private val scope: CoroutineScope
) {
    private var running: Job? = null

    /** Plans for [snapshot] and starts the work; returns the planned actions. */
    fun onQueueChanged(snapshot: QueueSnapshot): List<PrefetchAction> {
        running?.cancel()
        val actions = planner.plan(snapshot, target::isAvailable)
        if (actions.isEmpty()) return actions
        running = scope.launch {
            for ((index, action) in actions.withIndex()) {
                val done = try {
                    run(action)
                } catch (cancelled: CancellationException) {
                    actions.drop(index).forEach(planner::forget)
                    throw cancelled
                }
                if (!done) planner.forget(action)
            }
        }
        return actions
    }

    /** Stops the running work. */
    fun cancel() {
        running?.cancel()
        running = null
    }

    private suspend fun run(action: PrefetchAction): Boolean = when (action) {
        is PrefetchAction.RequestOnServer -> target.requestOnServer(action.id)
        is PrefetchAction.Preload -> target.preload(action.id, action.bytes)
    }
}
