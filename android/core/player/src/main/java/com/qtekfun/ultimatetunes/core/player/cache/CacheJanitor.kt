// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later

package com.qtekfun.ultimatetunes.core.player.cache

import com.qtekfun.ultimatetunes.core.api.model.SongId

/** The few cache operations the [CacheJanitor] needs (Media3's `Cache` in the app, a fake in tests). */
interface CacheView {
    /** Every key with cached content. */
    fun keys(): Set<String>

    /** The full length of [key]'s content, or null while unknown. */
    fun contentLength(key: String): Long?

    /** Bytes cached contiguously from the start of [key], up to [limit]. */
    fun cachedBytes(key: String, limit: Long): Long

    /** Removes everything cached for [key]. */
    fun remove(key: String)
}

/** Applies [CachePolicy] to what the cache holds. */
class CacheJanitor(private val cache: CacheView) {
    /**
     * Drops the `yt:` entries that [CachePolicy.disposition] rejects, keeping the [inUse] keys.
     * Returns the dropped keys with the reason.
     */
    fun sweep(inUse: Set<String>, archived: Set<SongId>): Map<String, DropReason> {
        val dropped = linkedMapOf<String, DropReason>()
        for (key in cache.keys().filter { CachePolicy.songOf(it).isExternal }) {
            val length = cache.contentLength(key)
            val entry = CacheEntry(key, length, cache.cachedBytes(key, length ?: Long.MAX_VALUE))
            val disposition = CachePolicy.disposition(entry, inUse, archived)
            if (disposition is Disposition.Drop) {
                cache.remove(key)
                dropped[key] = disposition.reason
            }
        }
        return dropped
    }
}
