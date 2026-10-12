// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.cache

import com.qtekfun.ultimatetunes.core.api.model.SongId

/**
 * The client cache rules (RF-12, SPEC §11 T03a). Every play goes through Media3's `SimpleCache`;
 * these rules say under which key, how big the cache may grow, and which entries must go.
 *
 * - The cache key is the **played id**: a library id, or the `yt:` id of a song that is still
 *   downloading on the server. The stream URL never takes part (it has no key, and the server
 *   root may change).
 * - A `yt:` entry is dropped once the song is archived (its library file is tagged and may be
 *   remuxed, so later plays fetch it under the library id), and after an **incomplete** first
 *   play (a retry on the server may change the format or the size, so a cached prefix could not
 *   be trusted).
 * - Library entries are only ever evicted by the LRU evictor.
 */
object CachePolicy {
    /** Default cache size (RF-12): 2 GB. */
    const val DEFAULT_CACHE_MB = 2048

    /** Smallest cache allowed, so the current and the next song always fit. */
    const val MIN_CACHE_MB = 256

    /** Read timeout of media requests: a first play waits for the server to start the download. */
    const val READ_TIMEOUT_SECONDS = 25L

    /** Bytes preloaded of the next song in the queue (prefetch, RF-12). */
    const val PRELOAD_BYTES = 512L * 1024

    private const val BYTES_PER_MB = 1024L * 1024

    /** The cache key of [id]: the played id itself. */
    fun cacheKey(id: SongId): String = id.value

    /** The song a cache [key] belongs to. */
    fun songOf(key: String): SongId = SongId(key)

    /** The cache size limit in bytes for a setting of [cacheSizeMb] megabytes. */
    fun maxBytes(cacheSizeMb: Int): Long = cacheSizeMb.coerceAtLeast(MIN_CACHE_MB) * BYTES_PER_MB

    /**
     * True when [cachedBytes] cover the whole content. A content whose length is still unknown
     * ([contentLength] null) is never complete: the server streamed it without a size and the
     * play did not reach its end.
     */
    fun isComplete(contentLength: Long?, cachedBytes: Long): Boolean =
        contentLength != null && contentLength >= 0 && cachedBytes >= contentLength

    /**
     * What to do with [entry]. [inUse] are the keys being played or prefetched right now (never
     * dropped while in use); [archived] are the `yt:` ids the server reported as archived.
     */
    fun disposition(entry: CacheEntry, inUse: Set<String>, archived: Set<SongId>): Disposition {
        val song = songOf(entry.key)
        return when {
            !song.isExternal || entry.key in inUse -> Disposition.Keep

            song in archived -> Disposition.Drop(DropReason.ARCHIVED)

            !isComplete(entry.contentLength, entry.cachedBytes) ->
                Disposition.Drop(DropReason.INCOMPLETE_FIRST_PLAY)

            else -> Disposition.Keep
        }
    }
}

/** What the cache holds for one key. */
data class CacheEntry(
    val key: String,
    /** Full length of the content in bytes, or null while unknown. */
    val contentLength: Long?,
    /** Bytes cached from the start of the content. */
    val cachedBytes: Long
)

/** The decision about one [CacheEntry]. */
sealed interface Disposition {
    data object Keep : Disposition

    data class Drop(val reason: DropReason) : Disposition
}

/** Why a `yt:` entry leaves the cache. */
enum class DropReason {
    /** The song is in the library now: later plays use its library id. */
    ARCHIVED,

    /** The first play stopped before the end (or the size was never known). */
    INCOMPLETE_FIRST_PLAY
}
