// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.gain

import com.qtekfun.ultimatetunes.core.api.model.AlbumId
import com.qtekfun.ultimatetunes.core.api.model.ReplayGain
import kotlin.math.pow

/**
 * ReplayGain (RF-04): the server computes track and album gain; the player turns them into a
 * volume. Album gain is used while the queue plays an album in order (the neighbouring song is
 * from the same album), track gain otherwise, each falling back to the other.
 *
 * The volume of a Media3 player only attenuates (0..1), so a positive gain is capped at unity, and
 * the peak keeps the result from clipping. Songs without ReplayGain (external songs, songs not
 * analysed yet) play at unity.
 */
object ReplayGainPolicy {
    private const val DB_PER_DECADE = 20.0

    /** True when the song between [previous] and [next] plays as part of album [current]. */
    fun isAlbumMode(previous: AlbumId?, current: AlbumId?, next: AlbumId?): Boolean =
        current != null && (previous == current || next == current)

    /** The player volume (0..1) for [gain]. */
    fun volume(gain: ReplayGain?, albumMode: Boolean): Float {
        val (db, peak) = when {
            gain == null -> null to null
            albumMode -> (gain.albumGain ?: gain.trackGain) to (gain.albumPeak ?: gain.trackPeak)
            else -> (gain.trackGain ?: gain.albumGain) to (gain.trackPeak ?: gain.albumPeak)
        }
        val linear = if (db == null) 1.0 else limit(10.0.pow(db / DB_PER_DECADE), peak)
        return linear.coerceIn(0.0, 1.0).toFloat()
    }

    /** [linear] lowered so that [peak] does not clip; an unknown (null or 0) peak is ignored. */
    private fun limit(linear: Double, peak: Double?): Double =
        if (peak != null && peak > 0) minOf(linear, 1 / peak) else linear
}
