// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.cache

import com.qtekfun.ultimatetunes.core.api.ErrorKind
import com.qtekfun.ultimatetunes.core.api.TunesError
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.api.model.TrackState
import com.qtekfun.ultimatetunes.core.api.model.TrackStatus
import java.io.IOException
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.currentTime
import kotlinx.coroutines.test.runTest
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.params.ParameterizedTest
import org.junit.jupiter.params.provider.EnumSource

private val YT = SongId("yt:dQw4w9WgXcQ")
private val LIBRARY = SongId("0190a5c8-7b1e-7c4a-9d1e-2f3a4b5c6d7e")

private fun status(state: TrackState, trackId: SongId? = null) = TunesResult.Success(
    TrackStatus(
        id = YT,
        trackId = trackId,
        state = state,
        progress = 0.5,
        attempts = 1,
        maxAttempts = 3,
        streamable = true
    )
)

class StatusPollPolicyTest {
    @Test
    fun `ready with a new library id means archived`() {
        assertEquals(
            PollStep.Archived(LIBRARY),
            StatusPollPolicy.next(YT, status(TrackState.READY, LIBRARY), 0)
        )
    }

    @Test
    fun `ready without a different library id ends the polling`() {
        assertEquals(PollStep.GiveUp, StatusPollPolicy.next(YT, status(TrackState.READY), 0))
        assertEquals(PollStep.GiveUp, StatusPollPolicy.next(YT, status(TrackState.READY, YT), 0))
    }

    @ParameterizedTest
    @EnumSource(TrackState::class, names = ["FAILED", "CANCELLED"])
    fun `failed and cancelled jobs stop the polling`(state: TrackState) {
        assertEquals(PollStep.Failed, StatusPollPolicy.next(YT, status(state), 0))
    }

    @ParameterizedTest
    @EnumSource(TrackState::class, names = ["NOT_REQUESTED", "QUEUED", "DOWNLOADING", "TAGGING"])
    fun `work in progress polls again`(state: TrackState) {
        assertEquals(PollStep.Again(2_000), StatusPollPolicy.next(YT, status(state), 0))
    }

    @Test
    fun `transient failures poll again, credential problems give up`() {
        val network = TunesResult.NetworkError(IOException("offline"))
        val api = TunesResult.ApiError(TunesError(ErrorKind.NOT_FOUND), 404)
        val protocol = TunesResult.ProtocolError("odd", 500)
        val unauthorized = TunesResult.Unauthorized(TunesError(ErrorKind.NOT_FOUND), 401)
        assertEquals(PollStep.Again(2_000), StatusPollPolicy.next(YT, network, 0))
        assertEquals(PollStep.Again(2_000), StatusPollPolicy.next(YT, api, 0))
        assertEquals(PollStep.Again(2_000), StatusPollPolicy.next(YT, protocol, 0))
        assertEquals(PollStep.GiveUp, StatusPollPolicy.next(YT, unauthorized, 0))
        assertEquals(PollStep.GiveUp, StatusPollPolicy.next(YT, TunesResult.NotConfigured, 0))
    }

    @Test
    fun `the delay doubles every three polls up to the cap`() {
        val delays = (0..12).map(StatusPollPolicy::delayFor)
        assertEquals(
            listOf(2_000L, 2_000, 2_000, 4_000, 4_000, 4_000, 8_000, 8_000, 8_000) +
                List(4) { 15_000L },
            delays
        )
        assertEquals(StatusPollPolicy.MAX_DELAY_MS, StatusPollPolicy.delayFor(1_000))
    }

    @Test
    fun `polling gives up after the maximum number of attempts`() {
        val last = StatusPollPolicy.MAX_ATTEMPTS - 1
        assertEquals(PollStep.GiveUp, StatusPollPolicy.next(YT, status(TrackState.QUEUED), last))
        assertTrue(
            StatusPollPolicy.next(YT, status(TrackState.QUEUED), last - 1) is PollStep.Again
        )
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
class StatusPollerTest {
    @Test
    fun `polls until archived and remembers the library id`() = runTest {
        val answers = ArrayDeque(
            listOf(
                status(TrackState.QUEUED),
                TunesResult.NetworkError(IOException("blip")),
                status(TrackState.DOWNLOADING),
                status(TrackState.READY, LIBRARY)
            )
        )
        val slept = mutableListOf<Long>()
        val poller = StatusPoller(fetch = { answers.removeFirst() }, sleep = { slept += it })

        assertEquals(PollStep.Archived(LIBRARY), poller.pollUntilSettled(YT))
        assertEquals(listOf(2_000L, 2_000, 2_000), slept)
        assertEquals(mapOf(YT to LIBRARY), poller.archived)
    }

    @Test
    fun `a failed download ends the polling without archiving`() = runTest {
        val poller = StatusPoller(fetch = { status(TrackState.FAILED) }, sleep = {})
        assertEquals(PollStep.Failed, poller.pollUntilSettled(YT))
        assertTrue(poller.archived.isEmpty())
    }

    @Test
    fun `a refused key ends the polling`() = runTest {
        val unauthorized = TunesResult.Unauthorized(TunesError(ErrorKind.INVALID_API_KEY), 401)
        val poller = StatusPoller(fetch = { unauthorized }, sleep = {})
        assertEquals(PollStep.GiveUp, poller.pollUntilSettled(YT))
    }

    @Test
    fun `a library id needs no polling`() = runTest {
        val poller = StatusPoller(fetch = { error("no call expected") })
        assertEquals(PollStep.GiveUp, poller.pollUntilSettled(LIBRARY))
    }

    @Test
    fun `the default sleep waits on the coroutine clock`() = runTest {
        val answers = ArrayDeque(listOf(status(TrackState.QUEUED), status(TrackState.CANCELLED)))
        val poller = StatusPoller(fetch = { answers.removeFirst() })
        assertEquals(PollStep.Failed, poller.pollUntilSettled(YT))
        assertEquals(2_000, currentTime)
    }
}
