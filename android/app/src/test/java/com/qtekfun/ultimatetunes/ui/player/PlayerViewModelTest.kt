// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.player

import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.fake.FakeTunesServer
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.api.model.TrackState
import com.qtekfun.ultimatetunes.playback.PlaybackState
import com.qtekfun.ultimatetunes.ui.FakePlayerController
import com.qtekfun.ultimatetunes.ui.MainDispatcherExtension
import com.qtekfun.ultimatetunes.ui.awaitFirst
import com.qtekfun.ultimatetunes.ui.connectedApi
import com.qtekfun.ultimatetunes.ui.dropConnection
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.tile
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.test.runTest
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.extension.ExtendWith

@ExtendWith(MainDispatcherExtension::class)
class PlayerViewModelTest {
    private lateinit var server: FakeTunesServer
    private lateinit var player: FakePlayerController
    private lateinit var viewModel: PlayerViewModel
    private val state get() = viewModel.state.value
    private val queue = listOf(tile(0), tile(1), tile(2))

    @BeforeEach
    fun setUp() {
        server = FakeTunesServer().start()
        player = FakePlayerController()
        viewModel = PlayerViewModel(player, connectedApi(server))
    }

    @AfterEach
    fun tearDown() {
        // Nothing may resume on Main once the test dispatcher is gone.
        viewModel.viewModelScope.cancel()
        server.close()
    }

    @Test
    fun `it connects to the session and shows its state in milliseconds`() {
        assertEquals(1, player.connects)
        player.mutableState.value = PlaybackState(
            queue = queue,
            index = 1,
            isPlaying = true,
            positionMs = 61_500,
            durationMs = 200_000,
            canSeek = true,
            connected = true
        )

        assertEquals(queue[1], state.current)
        assertEquals(61_500, state.positionMs)
        assertEquals(200_000, state.durationMs)
        assertTrue(state.canSeek)
        assertEquals(listOf(queue[2]), state.upNext)
        assertTrue(state.hasNext)
        assertTrue(state.hasPrevious)
    }

    @Test
    fun `play replaces the queue at the chosen song, and an empty queue is ignored`() {
        viewModel.play(queue, startIndex = 9)
        assertEquals(queue[2], state.current)
        assertEquals(Triple(2, 0L, true), player.played)

        viewModel.play(emptyList())
        assertEquals(queue, state.queue)
    }

    @Test
    fun `the controls reach the session`() {
        viewModel.play(queue)
        viewModel.next()
        assertEquals(1, state.index)
        viewModel.previous()
        assertEquals(0, state.index)
        viewModel.playAt(2)
        assertEquals(2, state.index)
        viewModel.togglePlayPause()
        assertFalse(state.isPlaying)

        viewModel.playNext(listOf(tile(7)))
        viewModel.enqueue(listOf(tile(8)))
        viewModel.playNext(emptyList())
        viewModel.enqueue(emptyList())
        assertEquals(
            listOf("song-0", "song-1", "song-2", "song-7", "song-8"),
            state.queue.map { it.id.value }
        )
    }

    @Test
    fun `seeking happens only where the song allows it`() {
        viewModel.play(queue)
        viewModel.seekTo(5_000)
        assertEquals(emptyList<Long>(), player.seeks)

        player.mutableState.update { it.copy(canSeek = true) }
        viewModel.seekTo(42_000)
        viewModel.seekTo(-3)
        assertEquals(listOf(42_000L, 0L), player.seeks)
    }

    @Test
    fun `a first play shows the server's progress while the song is fetched`() = runTest {
        server.dispatcher.trackStatusExample = "downloading"
        viewModel.play(listOf(tile(1, external = true), tile(2)))

        val shown = viewModel.state.awaitFirst { it.firstPlay != null }.firstPlay!!
        assertEquals(TrackState.DOWNLOADING, shown.state)
        assertEquals(0.42, shown.progress)
        assertFalse(shown.failed)
        assertTrue(server.takeRequest().url.encodedPath.endsWith("/status"))

        viewModel.next()
        assertNull(state.firstPlay)
    }

    @Test
    fun `a failed first play says so`() = runTest {
        server.dispatcher.trackStatusExample = "failed"
        viewModel.play(listOf(tile(1, external = true)))

        val shown = viewModel.state.awaitFirst { it.firstPlay != null }.firstPlay!!
        assertTrue(shown.failed)
    }

    @Test
    fun `a song already archived shows nothing`() = runTest {
        server.dispatcher.trackStatusExample = "ready"
        viewModel.play(listOf(tile(1, external = true)))

        server.takeRequest()
        assertNull(state.firstPlay)
    }

    @Test
    fun `a status check that fails leaves the player as it is`() = runTest {
        server.dispatcher.override("ut/v1/tracks/yt:Song1Abcdef/status") { dropConnection() }
        viewModel.play(listOf(tile(1, external = true)))

        server.takeRequest()
        assertNull(state.firstPlay)
    }

    @Test
    fun `a radio from the current song replaces what comes next`() = runTest {
        viewModel.play(listOf(tile(0), tile(5)))

        viewModel.startRadio()

        val after = viewModel.state.awaitFirst { state ->
            state.queue.none { it.id == SongId("song-5") }
        }
        assertEquals(SongId("song-0"), after.current?.id)
        assertEquals("Tidewater", after.queue[1].title)
        assertEquals("/ut/v1/radio", server.takeRequest().url.encodedPath)
    }

    @Test
    fun `a radio that cannot start is reported once`() = runTest {
        server.dispatcher.override("ut/v1/radio") { dropConnection() }
        viewModel.play(listOf(tile(0)))
        viewModel.startRadio()

        assertEquals(LoadError.NETWORK, viewModel.state.awaitFirst { it.message != null }.message)
        viewModel.dismissMessage()
        assertNull(state.message)
    }

    @Test
    fun `no radio without a song`() {
        viewModel.startRadio()
        assertNull(state.current)
    }
}
