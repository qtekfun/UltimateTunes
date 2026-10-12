// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.cache

import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.api.model.TrackState
import com.qtekfun.ultimatetunes.core.api.model.TrackStatus

/**
 * First-play status polling (RF-04, RF-05): while a `yt:` song plays, the player asks
 * `GET /ut/v1/tracks/{id}/status` until the server archives it (its `yt:` cache entry is then
 * dropped and the queue switches to the library id) or gives up on it.
 */
object StatusPollPolicy {
    /** First wait between polls. */
    const val BASE_DELAY_MS = 2_000L

    /** Longest wait between polls. */
    const val MAX_DELAY_MS = 15_000L

    /** Polls before giving up (about 30 minutes at the longest delay). */
    const val MAX_ATTEMPTS = 120

    /** What to do after poll number [attempt] (0-based) of [id] answered [result]. */
    fun next(id: SongId, result: TunesResult<TrackStatus>, attempt: Int): PollStep {
        if (attempt + 1 >= MAX_ATTEMPTS) return PollStep.GiveUp
        return when (result) {
            is TunesResult.Success -> afterStatus(id, result.value, attempt)

            // The key was refused or no server is set: polling again cannot help.
            is TunesResult.Unauthorized, TunesResult.NotConfigured -> PollStep.GiveUp

            // No answer or an odd one: try again later.
            is TunesResult.NetworkError, is TunesResult.ApiError, is TunesResult.ProtocolError ->
                PollStep.Again(delayFor(attempt))
        }
    }

    /** The wait before poll number [attempt] + 1: doubling from [BASE_DELAY_MS], capped. */
    fun delayFor(attempt: Int): Long {
        val shift = (attempt / DOUBLE_EVERY).coerceAtMost(MAX_SHIFT)
        return (BASE_DELAY_MS shl shift).coerceAtMost(MAX_DELAY_MS)
    }

    private fun afterStatus(id: SongId, status: TrackStatus, attempt: Int): PollStep =
        when (status.state) {
            TrackState.READY -> {
                val libraryId = status.trackId
                if (libraryId != null && libraryId != id) {
                    PollStep.Archived(libraryId)
                } else {
                    PollStep.GiveUp
                }
            }

            TrackState.FAILED, TrackState.CANCELLED -> PollStep.Failed

            // Not requested yet: the stream request starts the job, so look again soon.
            TrackState.NOT_REQUESTED, TrackState.QUEUED, TrackState.DOWNLOADING,
            TrackState.TAGGING -> PollStep.Again(delayFor(attempt))
        }

    /** Polls at the same delay before it doubles. */
    private const val DOUBLE_EVERY = 3

    /** 2 s << 3 = 16 s, already past [MAX_DELAY_MS]. */
    private const val MAX_SHIFT = 3
}

/** The outcome of one status poll. */
sealed interface PollStep {
    /** Poll again after [delayMs]. */
    data class Again(val delayMs: Long) : PollStep

    /** The song is in the library now, as [libraryId]. */
    data class Archived(val libraryId: SongId) : PollStep

    /** The download failed or was cancelled on the server. */
    data object Failed : PollStep

    /** Stop polling (nothing more to learn, or too many attempts). */
    data object GiveUp : PollStep
}
