// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.cache

import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.api.model.TrackStatus
import kotlinx.coroutines.delay

/**
 * Polls the status of a `yt:` song per [StatusPollPolicy] until it settles, and remembers which
 * `yt:` ids are archived (with their library id) for the [CacheJanitor] and the queue.
 */
class StatusPoller(
    private val fetch: suspend (SongId) -> TunesResult<TrackStatus>,
    private val sleep: suspend (Long) -> Unit = { delay(it) }
) {
    private val archivedIds = linkedMapOf<SongId, SongId>()

    /** The `yt:` ids known to be archived, each with its library id. */
    val archived: Map<SongId, SongId> get() = synchronized(archivedIds) { archivedIds.toMap() }

    /**
     * Polls [id] until it is archived, fails or the policy gives up, and returns that last step
     * ([PollStep.Archived], [PollStep.Failed] or [PollStep.GiveUp]). Library ids settle at once.
     * Cancel the calling coroutine to stop early (the song is no longer playing).
     */
    suspend fun pollUntilSettled(id: SongId): PollStep {
        var step: PollStep = PollStep.GiveUp
        var attempt = 0
        var polling = id.isExternal
        while (polling) {
            step = StatusPollPolicy.next(id, fetch(id), attempt++)
            when (val current = step) {
                is PollStep.Again -> sleep(current.delayMs)

                is PollStep.Archived -> {
                    synchronized(archivedIds) { archivedIds[id] = current.libraryId }
                    polling = false
                }

                PollStep.Failed, PollStep.GiveUp -> polling = false
            }
        }
        return step
    }
}
