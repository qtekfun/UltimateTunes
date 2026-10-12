// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.playback

import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.ui.connect.ConnectionGate
import com.qtekfun.ultimatetunes.ui.model.toTile
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.filter
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch

/**
 * When a song counts as played (RF-09 history): after half of it or [MAX_WAIT_MS], whichever
 * comes first, and only for songs longer than [MIN_LENGTH_MS] (the usual scrobbling rule).
 */
object ScrobbleRule {
    const val MIN_LENGTH_MS = 30_000L
    const val MAX_WAIT_MS = 240_000L

    fun isPlayed(positionMs: Long, durationMs: Long): Boolean =
        durationMs > MIN_LENGTH_MS && positionMs >= minOf(durationMs / 2, MAX_WAIT_MS)
}

/**
 * What the server keeps of the listening (RF-09), from the player's state while the app process
 * lives (the playback service keeps it alive while playing):
 * - **history**: "now playing" when a song starts, a play once [ScrobbleRule] says so (`scrobble`);
 * - **play queue across devices**: the queue of another device (`getPlayQueue`) is loaded, paused,
 *   when this one starts with an empty queue; changes to the queue, the current song and pauses
 *   are saved (`savePlayQueue`) a moment after they settle. An empty queue is never saved, so a
 *   fresh start never wipes the queue another device left.
 */
@Singleton
class ListeningSync internal constructor(
    private val player: PlayerController,
    private val api: TunesApi,
    private val gate: ConnectionGate,
    private val scope: CoroutineScope
) {
    @Inject
    constructor(player: PlayerController, api: TunesApi, gate: ConnectionGate) :
        this(player, api, gate, CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate))

    /** True once this connection's saved queue was looked at; saving starts only then. */
    @Volatile
    private var restored = false

    fun start() {
        scope.launch { gate.reconnects.collect { restored = false } }
        scope.launch { restoreQueues() }
        scope.launch { saveQueue() }
        scope.launch { scrobble() }
    }

    /** Each time the app is connected and the player reports its (maybe empty) queue. */
    private suspend fun restoreQueues() {
        combine(gate.needsConnect, player.state) { needsConnect, state ->
            !needsConnect && state.connected
        }.collect { ready ->
            if (ready && !restored) {
                restore()
                restored = true
            }
        }
    }

    private suspend fun restore() {
        if (player.state.value.queue.isNotEmpty()) return
        val saved = (api.playQueue() as? TunesResult.Success)?.value
        val tiles = saved?.entry.orEmpty().map { it.toTile(api) }
        // The user may have started something meanwhile: that wins.
        if (saved != null && tiles.isNotEmpty() && player.state.value.queue.isEmpty()) {
            val index = tiles.indexOfFirst { it.id == saved.current }.coerceAtLeast(0)
            player.play(tiles, index, saved.position ?: 0, playWhenReady = false)
        }
    }

    @OptIn(FlowPreview::class)
    private suspend fun saveQueue() {
        player.state
            .filter { restored && it.connected && it.queue.isNotEmpty() }
            .map { QueueSnapshot(it.queue.map { tile -> tile.id }, it.current?.id, it.isPlaying) }
            .distinctUntilChanged()
            .debounce(SAVE_DELAY_MS)
            .collect { snapshot ->
                api.savePlayQueue(
                    ids = snapshot.ids,
                    current = snapshot.current,
                    positionMillis = player.state.value.positionMs
                )
            }
    }

    private suspend fun scrobble() {
        var playing: Pair<Int, SongId>? = null
        var submitted = false
        player.state.collect { state ->
            val current = state.current ?: return@collect
            val key = state.index to current.id
            if (key != playing && state.isPlaying) {
                playing = key
                submitted = false
                api.scrobble(current.id, submission = false)
            }
            if (key == playing && !submitted &&
                ScrobbleRule.isPlayed(state.positionMs, state.durationMs)
            ) {
                submitted = true
                api.scrobble(current.id, submission = true)
            }
        }
    }

    private data class QueueSnapshot(
        val ids: List<SongId>,
        val current: SongId?,
        val playing: Boolean
    )

    companion object {
        /** Saves wait for the queue to settle this long. */
        const val SAVE_DELAY_MS = 3_000L
    }
}
