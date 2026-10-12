// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.player

import androidx.lifecycle.ViewModel
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update

/** What the mini player and the full player show. */
data class PlayerUiState(
    val queue: List<TrackTile> = emptyList(),
    val index: Int = 0,
    val isPlaying: Boolean = false,
    val positionSec: Int = 0
) {
    val current: TrackTile? get() = queue.getOrNull(index)
    val durationSec: Int get() = current?.durationSec ?: 0
    val hasNext: Boolean get() = index < queue.lastIndex
    val hasPrevious: Boolean get() = index > 0
    val upNext: List<TrackTile> get() = if (queue.isEmpty()) emptyList() else queue.drop(index + 1)
}

/**
 * The player's state for the UI: queue, current song, play/pause and position. PLAN T12 has no
 * real playback, so this only keeps the state the controls change; PLAN T17 connects it to the
 * Media3 session.
 */
@HiltViewModel
class PlayerViewModel @Inject constructor() : ViewModel() {
    private val mutableState = MutableStateFlow(PlayerUiState())
    val state: StateFlow<PlayerUiState> = mutableState.asStateFlow()

    /** Replaces the queue with [queue] and starts at [startIndex]. */
    fun play(queue: List<TrackTile>, startIndex: Int = 0) {
        if (queue.isEmpty()) return
        mutableState.value = PlayerUiState(
            queue = queue,
            index = startIndex.coerceIn(0, queue.lastIndex),
            isPlaying = true
        )
    }

    fun togglePlayPause() {
        mutableState.update { if (it.current == null) it else it.copy(isPlaying = !it.isPlaying) }
    }

    fun next() {
        mutableState.update {
            if (it.hasNext) it.copy(index = it.index + 1, positionSec = 0) else it
        }
    }

    /** Back to the start of the song, or to the previous one when already near the start. */
    fun previous() {
        mutableState.update {
            when {
                it.positionSec > RESTART_THRESHOLD_SEC -> it.copy(positionSec = 0)
                it.hasPrevious -> it.copy(index = it.index - 1, positionSec = 0)
                else -> it.copy(positionSec = 0)
            }
        }
    }

    /** Jumps to the song at [index] of the queue. */
    fun playAt(index: Int) {
        mutableState.update {
            if (index in it.queue.indices) {
                it.copy(index = index, positionSec = 0, isPlaying = true)
            } else {
                it
            }
        }
    }

    fun seekTo(positionSec: Int) {
        mutableState.update { it.copy(positionSec = positionSec.coerceIn(0, it.durationSec)) }
    }

    companion object {
        /** Seconds after which "previous" restarts the song instead of going back. */
        const val RESTART_THRESHOLD_SEC = 3
    }
}
