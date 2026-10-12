// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.playback

import com.qtekfun.ultimatetunes.ui.model.TrackTile
import kotlinx.coroutines.flow.StateFlow

/**
 * The player as the screens drive it (RF-11): its state, with positions in milliseconds, and its
 * commands. [PlaybackConnection] is the real one, over the Media3 session; tests use fakes.
 */
@Suppress("TooManyFunctions") // One function per player command the screens use.
interface PlayerController {
    val state: StateFlow<PlaybackState>

    /** Connects to the playback service now, so [state] starts following it. */
    fun connect()

    /** Replaces the queue with [queue] and starts at [startIndex], [startPositionMs]. */
    fun play(
        queue: List<TrackTile>,
        startIndex: Int = 0,
        startPositionMs: Long = 0,
        playWhenReady: Boolean = true
    )

    /** Adds [tiles] right after the current song. */
    fun playNext(tiles: List<TrackTile>)

    /** Adds [tiles] at the end of the queue. */
    fun enqueue(tiles: List<TrackTile>)

    /** Keeps the queue up to the current song and puts [tiles] after it (a radio from it). */
    fun replaceUpNext(tiles: List<TrackTile>)

    fun togglePlayPause()

    fun next()

    /** Back to the start of the song, or to the previous one when already near its start. */
    fun previous()

    /** Seeks to [positionMs] of the current song, only where the stream allows it (T03a). */
    fun seekTo(positionMs: Long)

    /** Jumps to the song at [index] of the queue. */
    fun playAt(index: Int)

    /** Stops and empties the queue. */
    fun clear()
}
