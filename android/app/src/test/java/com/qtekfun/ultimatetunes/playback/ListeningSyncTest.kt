// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.playback

import com.qtekfun.ultimatetunes.core.api.InMemoryServerConfigSource
import com.qtekfun.ultimatetunes.core.api.ServerConfig
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.core.api.model.ApiKeySecret
import com.qtekfun.ultimatetunes.core.api.model.PlayQueue
import com.qtekfun.ultimatetunes.core.api.model.Song
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.ui.FakePlayerController
import com.qtekfun.ultimatetunes.ui.connect.ConnectionGate
import com.qtekfun.ultimatetunes.ui.tile
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import java.time.Instant
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

@OptIn(ExperimentalCoroutinesApi::class)
class ListeningSyncTest {
    private val config = ServerConfig(
        "https://music.example.net/".toHttpUrl(),
        ApiKeySecret(FakeTunesServer.API_KEY)
    )
    private val source = InMemoryServerConfigSource(config)
    private val gate = ConnectionGate(source)
    private val player = FakePlayerController()
    private val saved = PlayQueue(
        current = SongId("song-2"),
        position = 73_500,
        username = "alice",
        changed = Instant.parse("2026-10-12T07:59:40Z"),
        changedBy = "Other phone",
        entry = listOf(song(1), song(2))
    )
    private val api = mockk<TunesApi>(relaxed = true) {
        coEvery { playQueue() } returns TunesResult.Success(saved)
        coEvery { savePlayQueue(any(), any(), any()) } returns TunesResult.Success(Unit)
        coEvery { scrobble(any(), any(), any()) } returns TunesResult.Success(Unit)
        every { coverArtUrl(any(), any()) } returns "https://music.example.net/c".toHttpUrl()
    }

    private fun song(n: Int) = Song(id = SongId("song-$n"), title = "Song $n", duration = 200)

    /** A sync running eagerly on the test's scheduler until the test ends. */
    private fun TestScope.started(): ListeningSync {
        val scope = CoroutineScope(
            backgroundScope.coroutineContext + UnconfinedTestDispatcher(testScheduler)
        )
        return ListeningSync(player, api, gate, scope).also { it.start() }
    }

    @Test
    fun `an empty player takes the queue another device saved, paused where it was`() = runTest {
        started()

        assertEquals(listOf("song-1", "song-2"), player.state.value.queue.map { it.id.value })
        assertEquals(Triple(1, 73_500L, false), player.played)
    }

    @Test
    fun `a player that already has a queue keeps it`() = runTest {
        player.mutableState.update { it.copy(queue = listOf(tile(7))) }
        started()

        assertNull(player.played)
        coVerify(exactly = 0) { api.playQueue() }
    }

    @Test
    fun `nothing is restored before the app is connected or the player answers`() = runTest {
        source.set(null)
        player.mutableState.update { it.copy(connected = false) }
        started()
        coVerify(exactly = 0) { api.playQueue() }

        source.set(config)
        coVerify(exactly = 0) { api.playQueue() }
        player.mutableState.update { it.copy(connected = true) }
        coVerify(exactly = 1) { api.playQueue() }
    }

    @Test
    fun `changes are saved once they settle, never an empty queue`() = runTest {
        coEvery { api.playQueue() } returns TunesResult.Success(null)
        started()
        player.play(listOf(tile(1), tile(2)), 0, 0, true)
        player.next()
        advanceTimeBy(ListeningSync.SAVE_DELAY_MS - 1)
        runCurrent()
        coVerify(exactly = 0) { api.savePlayQueue(any(), any(), any()) }

        player.mutableState.update { it.copy(positionMs = 12_000) }
        advanceTimeBy(2)
        runCurrent()
        coVerify(exactly = 1) {
            api.savePlayQueue(listOf(SongId("song-1"), SongId("song-2")), SongId("song-2"), 12_000)
        }

        player.clear()
        advanceTimeBy(ListeningSync.SAVE_DELAY_MS * 2)
        runCurrent()
        coVerify(exactly = 1) { api.savePlayQueue(any(), any(), any()) }
    }

    @Test
    fun `a pause is saved with its position`() = runTest {
        coEvery { api.playQueue() } returns TunesResult.Success(null)
        started()
        player.play(listOf(tile(1)), 0, 0, true)
        advanceTimeBy(ListeningSync.SAVE_DELAY_MS + 1)
        runCurrent()

        player.mutableState.update { it.copy(positionMs = 30_000) }
        player.togglePlayPause()
        advanceTimeBy(ListeningSync.SAVE_DELAY_MS + 1)
        runCurrent()

        coVerify { api.savePlayQueue(listOf(SongId("song-1")), SongId("song-1"), 30_000) }
    }

    @Test
    fun `a new connection restores again`() = runTest {
        started()
        player.clear()
        gate.disconnect()
        source.set(config)

        coVerify(exactly = 2) { api.playQueue() }
    }

    @Test
    fun `a song is reported as now playing, then as played after half of it`() = runTest {
        coEvery { api.playQueue() } returns TunesResult.Success(null)
        started()
        player.play(listOf(tile(1, durationSec = 200)), 0, 0, true)
        player.mutableState.update { it.copy(durationMs = 200_000) }
        coVerify(exactly = 1) { api.scrobble(SongId("song-1"), false, null) }

        player.mutableState.update { it.copy(positionMs = 99_000) }
        coVerify(exactly = 0) { api.scrobble(any(), true, any()) }
        player.mutableState.update { it.copy(positionMs = 100_000) }
        player.mutableState.update { it.copy(positionMs = 150_000) }
        coVerify(exactly = 1) { api.scrobble(SongId("song-1"), true, null) }
    }

    @Test
    fun `nothing is reported while paused or without a song`() = runTest {
        coEvery { api.playQueue() } returns TunesResult.Success(null)
        started()
        player.play(listOf(tile(1)), 0, 0, playWhenReady = false)

        coVerify(exactly = 0) { api.scrobble(any(), any(), any()) }
    }

    @Test
    fun `the scrobble rule`() {
        assertFalse(ScrobbleRule.isPlayed(positionMs = 29_000, durationMs = 30_000))
        assertFalse(ScrobbleRule.isPlayed(positionMs = 99_999, durationMs = 200_000))
        assertTrue(ScrobbleRule.isPlayed(positionMs = 100_000, durationMs = 200_000))
        assertTrue(ScrobbleRule.isPlayed(positionMs = 240_000, durationMs = 3_600_000))
        assertFalse(ScrobbleRule.isPlayed(positionMs = 239_999, durationMs = 3_600_000))
    }

    @Test
    fun `a queue that could not be read is tried again, and nothing is saved meanwhile`() =
        runTest {
            coEvery { api.playQueue() } returns TunesResult.NetworkError(java.io.IOException("x"))
            started()
            player.mutableState.update { it.copy(positionMs = 1) }
            coVerify(exactly = 2) { api.playQueue() }

            coEvery { api.playQueue() } returns TunesResult.Success(saved)
            player.mutableState.update { it.copy(positionMs = 2) }
            assertEquals(Triple(1, 73_500L, false), player.played)
            player.mutableState.update { it.copy(positionMs = 3) }
            coVerify(exactly = 3) { api.playQueue() }
        }
}
