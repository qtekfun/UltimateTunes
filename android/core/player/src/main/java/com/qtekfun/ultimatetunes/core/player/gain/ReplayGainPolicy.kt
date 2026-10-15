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
 * analysed yet, offline songs whose gain is not known) play at [unknownDb]: at unity they would be
 * some 10 dB louder than the attenuated library songs around them.
 */
object ReplayGainPolicy {
    private const val DB_PER_DECADE = 20.0

    /**
     * The gain of a song with no ReplayGain while no library song has been seen: a typical modern
     * master (about -9 LUFS) brought to the -18 LUFS reference of the server's ReplayGain.
     */
    const val DEFAULT_UNKNOWN_DB = -9.0

    /** True when the song between [previous] and [next] plays as part of album [current]. */
    fun isAlbumMode(previous: AlbumId?, current: AlbumId?, next: AlbumId?): Boolean =
        current != null && (previous == current || next == current)

    /** The player volume (0..1) for [gain]; [unknownDb] stands in when there is no gain. */
    fun volume(
        gain: ReplayGain?,
        albumMode: Boolean,
        unknownDb: Double = DEFAULT_UNKNOWN_DB
    ): Float {
        val (db, peak) = when {
            gain == null -> null to null
            albumMode -> (gain.albumGain ?: gain.trackGain) to (gain.albumPeak ?: gain.trackPeak)
            else -> (gain.trackGain ?: gain.albumGain) to (gain.trackPeak ?: gain.albumPeak)
        }
        val linear = if (db == null) linear(unknownDb) else limit(linear(db), peak)
        return linear.coerceIn(0.0, 1.0).toFloat()
    }

    private fun linear(db: Double) = 10.0.pow(db / DB_PER_DECADE)

    /** [linear] lowered so that [peak] does not clip; an unknown (null or 0) peak is ignored. */
    private fun limit(linear: Double, peak: Double?): Double =
        if (peak != null && peak > 0) minOf(linear, 1 / peak) else linear
}
