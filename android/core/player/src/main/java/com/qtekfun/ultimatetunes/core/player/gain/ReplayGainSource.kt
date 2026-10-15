// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.gain

import com.qtekfun.ultimatetunes.core.api.TunesApi
import com.qtekfun.ultimatetunes.core.api.TunesResult
import com.qtekfun.ultimatetunes.core.api.model.ReplayGain
import com.qtekfun.ultimatetunes.core.api.model.SongId

/**
 * The ReplayGain of library songs, from `getSong`, remembered for the last [capacity] songs.
 * External songs have none. A failed lookup is not remembered, so it is tried again next time.
 */
class ReplayGainSource(private val api: TunesApi, private val capacity: Int = DEFAULT_CAPACITY) {
    private val known = object : LinkedHashMap<SongId, ReplayGain?>(capacity, LOAD_FACTOR, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<SongId, ReplayGain?>) =
            size > capacity
    }

    /** The ReplayGain of [id], or null when it has none or the server could not be asked. */
    suspend fun gainOf(id: SongId): ReplayGain? {
        if (id.isExternal) return null
        val remembered = remembered(id)
        return if (remembered.first) remembered.second else fetch(id)
    }

    /** Whether the gain of [id] is already known without asking the server, and that gain. */
    fun remembered(id: SongId): Pair<Boolean, ReplayGain?> =
        synchronized(known) { known.containsKey(id) to known[id] }

    /**
     * The gain for a song without ReplayGain: the mean track gain of the remembered library songs,
     * so it plays about as loud as the music around it, or [ReplayGainPolicy.DEFAULT_UNKNOWN_DB].
     */
    fun unknownDb(): Double {
        val seen = synchronized(known) {
            known.values.mapNotNull { it?.trackGain ?: it?.albumGain }
        }
        return if (seen.isEmpty()) ReplayGainPolicy.DEFAULT_UNKNOWN_DB else seen.average()
    }

    private suspend fun fetch(id: SongId): ReplayGain? {
        val song = (api.song(id) as? TunesResult.Success)?.value ?: return null
        synchronized(known) { known[id] = song.replayGain }
        return song.replayGain
    }

    private companion object {
        const val DEFAULT_CAPACITY = 256
        const val LOAD_FACTOR = 0.75f
    }
}
