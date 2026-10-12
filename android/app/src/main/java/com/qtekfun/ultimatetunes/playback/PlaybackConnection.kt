// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.playback

import android.content.ComponentName
import android.content.Context
import androidx.media3.common.C
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import com.google.common.util.concurrent.ListenableFuture
import com.google.common.util.concurrent.MoreExecutors
import com.qtekfun.ultimatetunes.core.player.media.MediaItems
import com.qtekfun.ultimatetunes.core.player.session.PlaybackService
import com.qtekfun.ultimatetunes.ui.connect.ConnectionGate
import com.qtekfun.ultimatetunes.ui.model.TrackTile
import dagger.hilt.android.qualifiers.ApplicationContext
import java.util.concurrent.ExecutionException
import javax.inject.Inject
import javax.inject.Singleton
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine

/** Why the current song cannot play. */
enum class PlaybackIssue {
    /** No connection to the server (or it timed out). */
    NETWORK,

    /** The server refused or does not have it (e.g. its download failed). */
    NOT_AVAILABLE,

    /** Anything else: the file could not be decoded, and so on. */
    UNPLAYABLE
}

/** What the player screens show, with positions in **milliseconds** (lyrics need them). */
data class PlaybackState(
    val queue: List<TrackTile> = emptyList(),
    val index: Int = 0,
    val isPlaying: Boolean = false,
    val isBuffering: Boolean = false,
    val positionMs: Long = 0,
    /** Length of the current song; from its metadata until the player knows better. */
    val durationMs: Long = 0,
    /** False while a `yt:` song streams without a known size (no seek, T03a). */
    val canSeek: Boolean = false,
    val issue: PlaybackIssue? = null,
    /** True once the state comes from the playback service (an empty queue is then real). */
    val connected: Boolean = false
) {
    val current: TrackTile? get() = queue.getOrNull(index)
    val hasNext: Boolean get() = index < queue.lastIndex
    val hasPrevious: Boolean get() = index > 0
    val upNext: List<TrackTile> get() = if (queue.isEmpty()) emptyList() else queue.drop(index + 1)
}

/**
 * The app's handle on the playback service (RF-11): a Media3 `MediaController` bound to
 * [PlaybackService], with its state as a flow and the commands the mini and full player need.
 * Commands sent before the controller is connected wait for it. Going back to the Connect screen
 * stops playback and clears the queue (another server or key must not inherit it).
 */
@Suppress("TooManyFunctions") // One function per player command the screens use.
@Singleton
class PlaybackConnection @Inject constructor(
    @param:ApplicationContext private val context: Context,
    private val gate: ConnectionGate
) : PlayerController {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val mutableState = MutableStateFlow(PlaybackState())
    private var ticker: Job? = null

    /** The player's state, updated on every change and every [TICK_MS] while playing. */
    override val state: StateFlow<PlaybackState> = mutableState.asStateFlow()

    private var controller: Deferred<MediaController>? = null

    init {
        scope.launch {
            gate.reconnects.collect { if (controller?.isCompleted == true) clear() }
        }
    }

    /** Connects to the service now (the state flow starts following the player). */
    override fun connect() {
        controller()
    }

    /** The controller, connecting (again, after a failed attempt) when needed. */
    private fun controller(): Deferred<MediaController> {
        val current = controller
        // A failed attempt counts as cancelled: connect again.
        if (current != null && !current.isCancelled) return current
        return scope.async {
            val token = SessionToken(context, ComponentName(context, PlaybackService::class.java))
            MediaController.Builder(context, token).buildAsync().await().also { controller ->
                controller.addListener(object : Player.Listener {
                    override fun onEvents(player: Player, events: Player.Events) = publish(player)
                })
                publish(controller)
            }
        }.also { controller = it }
    }

    override fun play(
        queue: List<TrackTile>,
        startIndex: Int,
        startPositionMs: Long,
        playWhenReady: Boolean
    ) = command {
        if (queue.isEmpty()) return@command
        it.setMediaItems(
            queue.map { tile -> MediaItems.of(tile.toPlayable()) },
            startIndex.coerceIn(0, queue.lastIndex),
            startPositionMs
        )
        it.playWhenReady = playWhenReady
        it.prepare()
    }

    override fun playNext(tiles: List<TrackTile>) = command {
        val at = if (it.mediaItemCount == 0) 0 else it.currentMediaItemIndex + 1
        it.addMediaItems(at, tiles.map { tile -> MediaItems.of(tile.toPlayable()) })
    }

    override fun enqueue(tiles: List<TrackTile>) = command {
        it.addMediaItems(tiles.map { tile -> MediaItems.of(tile.toPlayable()) })
    }

    override fun replaceUpNext(tiles: List<TrackTile>) = command {
        if (it.mediaItemCount == 0) return@command
        val after = it.currentMediaItemIndex + 1
        if (after < it.mediaItemCount) it.removeMediaItems(after, it.mediaItemCount)
        it.addMediaItems(tiles.map { tile -> MediaItems.of(tile.toPlayable()) })
    }

    override fun togglePlayPause() = command {
        if (it.isPlaying) {
            it.pause()
        } else {
            if (it.playbackState == Player.STATE_IDLE) it.prepare()
            if (it.playbackState == Player.STATE_ENDED) it.seekToDefaultPosition()
            it.play()
        }
    }

    override fun next() = command { it.seekToNextMediaItem() }

    override fun previous() = command { it.seekToPrevious() }

    override fun seekTo(positionMs: Long) = command {
        if (it.isCurrentMediaItemSeekable) it.seekTo(positionMs.coerceAtLeast(0))
    }

    override fun playAt(index: Int) = command {
        if (index in 0 until it.mediaItemCount) {
            it.seekToDefaultPosition(index)
            it.play()
        }
    }

    override fun clear() = command {
        it.stop()
        it.clearMediaItems()
    }

    private fun command(block: (MediaController) -> Unit) {
        scope.launch {
            try {
                block(controller().await())
            } catch (ignored: SecurityException) {
                // The session refused this app: nothing to control. The next command retries.
                mutableState.value = mutableState.value.copy(issue = PlaybackIssue.UNPLAYABLE)
                controller = null
            }
        }
    }

    private fun publish(player: Player) {
        val queue = (0 until player.mediaItemCount).map {
            MediaItems.trackOf(player.getMediaItemAt(it)).toTile()
        }
        val index = player.currentMediaItemIndex.coerceAtLeast(0)
        val metadataMs = queue.getOrNull(index)?.durationSec?.let { it * MS_PER_SECOND } ?: 0
        mutableState.value = PlaybackState(
            queue = queue,
            index = index,
            isPlaying = player.isPlaying,
            isBuffering = player.playbackState == Player.STATE_BUFFERING,
            positionMs = player.currentPosition.coerceAtLeast(0),
            durationMs = player.duration.takeIf { it != C.TIME_UNSET } ?: metadataMs,
            canSeek = player.isCurrentMediaItemSeekable,
            issue = player.playerError?.let(::issueOf),
            connected = true
        )
        if (player.isPlaying) startTicker(player) else stopTicker()
    }

    private fun startTicker(player: Player) {
        if (ticker?.isActive == true) return
        ticker = scope.launch {
            while (isActive) {
                delay(TICK_MS)
                mutableState.value = mutableState.value.copy(
                    positionMs = player.currentPosition.coerceAtLeast(0)
                )
            }
        }
    }

    private fun stopTicker() {
        ticker?.cancel()
        ticker = null
    }

    companion object {
        /** Position updates while playing; fine enough for the scrubber and synced lyrics. */
        const val TICK_MS = 200L
        private const val MS_PER_SECOND = 1000L

        /** The [PlaybackIssue] of [error]. */
        fun issueOf(error: PlaybackException): PlaybackIssue = when (error.errorCode) {
            PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_FAILED,
            PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT,
            PlaybackException.ERROR_CODE_TIMEOUT -> PlaybackIssue.NETWORK

            PlaybackException.ERROR_CODE_IO_BAD_HTTP_STATUS,
            PlaybackException.ERROR_CODE_IO_FILE_NOT_FOUND,
            PlaybackException.ERROR_CODE_IO_NO_PERMISSION -> PlaybackIssue.NOT_AVAILABLE

            else -> PlaybackIssue.UNPLAYABLE
        }
    }
}

/** Waits for a Media3 future without blocking. */
private suspend fun <T> ListenableFuture<T>.await(): T = suspendCancellableCoroutine { cont ->
    addListener(
        {
            try {
                cont.resume(get())
            } catch (failed: ExecutionException) {
                cont.resumeWithException(failed.cause ?: failed)
            }
        },
        MoreExecutors.directExecutor()
    )
    cont.invokeOnCancellation { cancel(false) }
}
