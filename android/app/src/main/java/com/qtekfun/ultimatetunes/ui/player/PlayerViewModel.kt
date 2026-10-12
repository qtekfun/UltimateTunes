// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.ui.player

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.api.model.TrackState
import com.qtekfun.ultimatetunes.playback.PlaybackIssue
import com.qtekfun.ultimatetunes.playback.PlaybackState
import com.qtekfun.ultimatetunes.playback.PlayerController
import com.qtekfun.ultimatetunes.ui.model.LoadError
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import com.qtekfun.ultimatetunes.ui.model.toLoadError
import com.qtekfun.ultimatetunes.ui.model.toTile
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

/**
 * A song not in the library yet, while the server fetches it for its first play (RF-05): the job
 * state and its progress (0..1) from `GET /ut/v1/tracks/{id}/status`.
 */
data class FirstPlay(val state: TrackState, val progress: Double) {
    val failed: Boolean get() = state == TrackState.FAILED || state == TrackState.CANCELLED
}

/** What the mini player and the full player show, with positions in **milliseconds**. */
data class PlayerUiState(
    val queue: List<TrackTile> = emptyList(),
    val index: Int = 0,
    val isPlaying: Boolean = false,
    val isBuffering: Boolean = false,
    val positionMs: Long = 0,
    val durationMs: Long = 0,
    /** False while a song streams without a known size (no seek on a first play, T03a). */
    val canSeek: Boolean = false,
    val issue: PlaybackIssue? = null,
    /** The current song's first play on the server, while it is being fetched. */
    val firstPlay: FirstPlay? = null,
    /** A radio that could not start, shown once. */
    val message: LoadError? = null
) {
    val current: TrackTile? get() = queue.getOrNull(index)
    val hasNext: Boolean get() = index < queue.lastIndex
    val hasPrevious: Boolean get() = index > 0
    val upNext: List<TrackTile> get() = if (queue.isEmpty()) emptyList() else queue.drop(index + 1)
}

/**
 * The player for the UI (RF-11): the state of the Media3 session through [PlayerController] and
 * its commands, plus what the session does not know: the progress of a first play of a song that
 * is not in the library yet (polled while it is current) and the radio from the current song
 * (`GET /ut/v1/radio`).
 */
@Suppress("TooManyFunctions") // One function per player control.
@HiltViewModel
class PlayerViewModel @Inject constructor(
    private val player: PlayerController,
    private val api: TunesApi
) : ViewModel() {
    private val firstPlay = MutableStateFlow<Pair<SongId, FirstPlay>?>(null)
    private val message = MutableStateFlow<LoadError?>(null)

    val state: StateFlow<PlayerUiState> =
        combine(player.state, firstPlay, message) { playback, first, message ->
            playback.toUi(
                firstPlay = first?.takeIf { it.first == playback.current?.id }?.second,
                message = message
            )
        }.stateIn(viewModelScope, SharingStarted.Eagerly, player.state.value.toUi(null, null))

    init {
        player.connect()
        viewModelScope.launch {
            player.state
                .map { it.current?.id?.takeIf(SongId::isExternal) }
                .distinctUntilChanged()
                .collectLatest { id ->
                    firstPlay.value = null
                    if (id != null) followFirstPlay(id)
                }
        }
    }

    /** Replaces the queue with [queue] and starts at [startIndex]. */
    fun play(queue: List<TrackTile>, startIndex: Int = 0) {
        if (queue.isEmpty()) return
        player.play(queue, startIndex.coerceIn(0, queue.lastIndex))
    }

    /** Puts [tracks] right after the current song. */
    fun playNext(tracks: List<TrackTile>) {
        if (tracks.isNotEmpty()) player.playNext(tracks)
    }

    /** Puts [tracks] at the end of the queue. */
    fun enqueue(tracks: List<TrackTile>) {
        if (tracks.isNotEmpty()) player.enqueue(tracks)
    }

    fun togglePlayPause() = player.togglePlayPause()

    fun next() = player.next()

    fun previous() = player.previous()

    /** Jumps to the song at [index] of the queue. */
    fun playAt(index: Int) = player.playAt(index)

    /** Seeks to [positionMs], only where the song allows it. */
    fun seekTo(positionMs: Long) {
        if (state.value.canSeek) player.seekTo(positionMs.coerceAtLeast(0))
    }

    /**
     * Starts a radio from the current song (RF-06): it keeps playing and the radio's songs replace
     * what was coming up.
     */
    fun startRadio() {
        val current = state.value.current ?: return
        viewModelScope.launch {
            when (val result = api.radio(current.id, RADIO_LENGTH)) {
                is TunesResult.Success -> player.replaceUpNext(
                    result.value.items
                        .filterNot { it.id == current.id }
                        .map { it.toTile(api) }
                )

                is TunesResult.Failure -> message.value = result.toLoadError()
            }
        }
    }

    fun dismissMessage() {
        message.value = null
    }

    /** Polls the first play of [id] while the server is still fetching it. */
    private suspend fun followFirstPlay(id: SongId) {
        repeat(MAX_POLLS) {
            val status = (api.trackStatus(id) as? TunesResult.Success)?.value ?: return
            val waiting = status.state.isInProgress || status.state == TrackState.NOT_REQUESTED
            val shown = FirstPlay(status.state, status.progress)
            firstPlay.value = if (waiting || shown.failed) id to shown else null
            if (!waiting) return
            delay(POLL_MS)
        }
    }

    private fun PlaybackState.toUi(firstPlay: FirstPlay?, message: LoadError?) = PlayerUiState(
        queue = queue,
        index = index,
        isPlaying = isPlaying,
        isBuffering = isBuffering,
        positionMs = positionMs,
        durationMs = durationMs,
        canSeek = canSeek,
        issue = issue,
        firstPlay = firstPlay,
        message = message
    )

    companion object {
        /** How often the first play of a song not in the library yet is checked. */
        const val POLL_MS = 1_500L

        /** At most this many checks (several minutes): a first play that long has stalled. */
        const val MAX_POLLS = 200

        /** Songs a radio started from the player queues. */
        const val RADIO_LENGTH = 50
    }
}
