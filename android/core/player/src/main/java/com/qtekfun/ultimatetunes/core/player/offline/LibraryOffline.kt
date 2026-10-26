// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.offline

import com.qtekfun.ultimatetunes.core.api.model.Song
import com.qtekfun.ultimatetunes.core.api.model.SongId
import com.qtekfun.ultimatetunes.core.player.PlayableTrack
import kotlinx.serialization.Serializable

/**
 * "Keep my whole library offline" (RF-12): the part of the library kept on the phone because of
 * that setting. It is a third source of wanted songs next to single songs and collections, so the
 * same sync downloads and frees it.
 */
@Serializable
data class LibraryOffline(
    /** The songs chosen at the last successful sync; null until the first one. */
    val songs: List<PlayableTrack>? = null,
    /** What the last sync found and what it left out; null until the first sync. */
    val report: LibraryReport? = null
)

/**
 * How the library compares with the limit. Songs the user keeps on their own (an explicit song,
 * album or playlist) are not counted: they are on the phone anyway and never evicted.
 */
@Serializable
data class LibraryReport(
    val totalCount: Int,
    val totalBytes: Long,
    val keptCount: Int,
    val keptBytes: Long,
    /** True when some song had no size and its bytes are estimated from bitrate and duration. */
    val estimated: Boolean
) {
    val leftOutCount: Int get() = totalCount - keptCount
    val leftOutBytes: Long get() = totalBytes - keptBytes
}

/** One library song as the priority logic sees it: small enough to keep a whole library. */
data class LibraryCandidate(
    val id: SongId,
    val bytes: Long,
    val estimated: Boolean,
    val starred: Boolean,
    val playCount: Long,
    val createdMs: Long
) {
    companion object {
        /** Used when a song has neither a size nor a bitrate and duration: a typical Opus song. */
        const val FALLBACK_BYTES = 4L * 1024 * 1024

        private const val BITS_PER_BYTE = 8L
        private const val BITS_PER_KBIT = 1000L

        fun of(song: Song): LibraryCandidate {
            val known = song.size?.takeIf { it > 0 }
            val bitRate = song.bitRate?.takeIf { it > 0 }
            val seconds = song.duration?.takeIf { it > 0 }
            val bytes = known
                ?: if (bitRate != null && seconds != null) {
                    bitRate.toLong() * BITS_PER_KBIT / BITS_PER_BYTE * seconds
                } else {
                    FALLBACK_BYTES
                }
            return LibraryCandidate(
                id = song.id,
                bytes = bytes,
                estimated = known == null,
                starred = song.starred != null,
                playCount = song.playCount ?: 0,
                createdMs = song.created?.toEpochMilli() ?: 0
            )
        }
    }
}

/** The result of fitting a library into a limit. */
data class LibrarySelection(val chosen: List<LibraryCandidate>, val report: LibraryReport)

/**
 * Which library songs fit in the limit (RF-12). Priority: starred songs first, then the most
 * played, then the most recently added. The first song that does not fit ends the selection, so
 * a song is never kept while one above it is left out. The same input always gives the same
 * answer (ties break on the id), so a sync does not swap songs for nothing.
 */
object LibrarySelector {
    private val PRIORITY = compareByDescending<LibraryCandidate> { it.starred }
        .thenByDescending { it.playCount }
        .thenByDescending { it.createdMs }
        .thenBy { it.id.value }

    /**
     * Fits [candidates] into [limitBytes]. Songs in [alreadyKept] (kept explicitly) are on the
     * phone anyway: they cost none of the limit and are not part of the result. Every other
     * candidate counts once, by id.
     */
    fun select(
        candidates: List<LibraryCandidate>,
        limitBytes: Long,
        alreadyKept: Set<SongId> = emptySet()
    ): LibrarySelection {
        val own = candidates.filter { it.id !in alreadyKept }.distinctBy { it.id }
        val chosen = ArrayList<LibraryCandidate>()
        var used = 0L
        for (candidate in own.sortedWith(PRIORITY)) {
            if (used + candidate.bytes > limitBytes) break
            used += candidate.bytes
            chosen += candidate
        }
        return LibrarySelection(
            chosen = chosen,
            report = LibraryReport(
                totalCount = own.size,
                totalBytes = own.sumOf { it.bytes },
                keptCount = chosen.size,
                keptBytes = used,
                estimated = own.any { it.estimated }
            )
        )
    }
}
