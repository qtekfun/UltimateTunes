// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.player

import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class PlayerViewModelTest {
    private fun track(n: Int, duration: Int? = 200) = TrackTile(
        id = SongId("song-$n"),
        title = "Song $n",
        artist = "Invented Artist",
        album = null,
        durationSec = duration,
        coverUrl = null,
        isExternal = false
    )

    private val queue = listOf(track(0), track(1), track(2))
    private val viewModel = PlayerViewModel()
    private val state get() = viewModel.state.value

    @Test
    fun `nothing plays at first`() {
        assertNull(state.current)
        assertFalse(state.isPlaying)
        assertEquals(0, state.durationSec)
        assertEquals(emptyList<TrackTile>(), state.upNext)
        viewModel.togglePlayPause()
        assertFalse(state.isPlaying)
    }

    @Test
    fun `play starts the queue at the given song`() {
        viewModel.play(queue, startIndex = 1)

        assertEquals(track(1), state.current)
        assertTrue(state.isPlaying)
        assertEquals(listOf(track(2)), state.upNext)
        assertTrue(state.hasNext)
        assertTrue(state.hasPrevious)
    }

    @Test
    fun `play clamps the start and ignores an empty queue`() {
        viewModel.play(queue, startIndex = 9)
        assertEquals(track(2), state.current)
        viewModel.play(queue, startIndex = -1)
        assertEquals(track(0), state.current)

        viewModel.play(emptyList())
        assertEquals(track(0), state.current)
    }

    @Test
    fun `play and pause toggle`() {
        viewModel.play(queue)
        viewModel.togglePlayPause()
        assertFalse(state.isPlaying)
        viewModel.togglePlayPause()
        assertTrue(state.isPlaying)
    }

    @Test
    fun `next moves on and stops at the end`() {
        viewModel.play(queue)
        viewModel.seekTo(50)
        viewModel.next()
        assertEquals(1, state.index)
        assertEquals(0, state.positionSec)
        viewModel.next()
        viewModel.next()
        assertEquals(2, state.index)
        assertFalse(state.hasNext)
    }

    @Test
    fun `previous restarts the song after a few seconds, else goes back`() {
        viewModel.play(queue, startIndex = 1)
        viewModel.seekTo(PlayerViewModel.RESTART_THRESHOLD_SEC + 1)
        viewModel.previous()
        assertEquals(1, state.index)
        assertEquals(0, state.positionSec)

        viewModel.previous()
        assertEquals(0, state.index)

        viewModel.seekTo(2)
        viewModel.previous()
        assertEquals(0, state.index)
        assertEquals(0, state.positionSec)
    }

    @Test
    fun `playAt jumps inside the queue only`() {
        viewModel.play(queue)
        viewModel.togglePlayPause()
        viewModel.playAt(2)
        assertEquals(2, state.index)
        assertTrue(state.isPlaying)
        viewModel.playAt(3)
        assertEquals(2, state.index)
    }

    @Test
    fun `seek stays inside the song`() {
        viewModel.play(listOf(track(0, duration = 100)))
        viewModel.seekTo(40)
        assertEquals(40, state.positionSec)
        viewModel.seekTo(500)
        assertEquals(100, state.positionSec)
        viewModel.seekTo(-5)
        assertEquals(0, state.positionSec)
    }

    @Test
    fun `a song without a known duration cannot be scrubbed`() {
        viewModel.play(listOf(track(0, duration = null)))
        viewModel.seekTo(30)
        assertEquals(0, state.positionSec)
    }
}
